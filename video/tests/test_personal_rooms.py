"""A member's private meeting room (task #687).

The invariant under test throughout: *nobody but the owner is in a personal room
unless the owner is in it* — for every kind of entrant, with no exception for the
site-technical roles.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from core.models import StaffRole
from video import services_personal as personal
from video.models import DailyRoom, PersonalRoom, RoomInvitation

from .factories import daily_on

pytestmark = pytest.mark.django_db


def member(email="member@example.com", *, first="Ada", last="Lovelace"):
    u = User.objects.create_user(email=email, password="x", first_name=first, last_name=last)
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def grant(user, key):
    """Give ``user`` a StaffRole. The rows are seeded by a data migration, so
    this gets the existing one rather than creating a duplicate key."""
    role, _ = StaffRole.objects.get_or_create(key=key, defaults={"name": key})
    role.holders.add(user)
    return role


def non_member(email="outsider@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.EXTERNAL
    u.profile.save()
    return u


def room_for(user):
    room = personal.personal_room_for(user, create=True)
    # A DailyRoom row is what presence is read against; provisioning it here
    # keeps these tests off the Daily API entirely.
    DailyRoom.objects.create(
        personal_room=room, name=f"lsp-{room.slug}",
        url=f"https://lsp.daily.co/lsp-{room.slug}", provider_created=True,
    )
    return room


@pytest.fixture
def present(monkeypatch):
    """Control whether the room's owner is 'in the room'."""
    state = {"live": False}

    def _count(daily_room):
        return 1 if state["live"] else 0

    monkeypatch.setattr("video.services.room_participant_count", _count)
    return state


# ---- who gets a room ----------------------------------------------------

def test_member_gets_a_room_lazily():
    u = member()
    assert personal.personal_room_for(u) is None
    room = personal.personal_room_for(u, create=True)
    assert room is not None
    assert personal.personal_room_for(u, create=True).pk == room.pk


def test_non_member_gets_no_room():
    assert personal.personal_room_for(non_member(), create=True) is None


def test_room_defaults_are_closed():
    room = personal.personal_room_for(member(), create=True)
    assert room.recording_mode == PersonalRoom.RecordingMode.OFF
    assert room.office_hours == PersonalRoom.OfficeHours.OFF
    assert not room.advertises_hours
    assert not room.admits_members


def test_slug_is_opaque_not_the_directory_handle():
    """Daily's room name rides in the iframe URL, where a guest can read it."""
    u = member(first="Ada", last="Lovelace")
    room = personal.personal_room_for(u, create=True)
    assert room.slug.startswith("pr-")
    assert "ada" not in room.slug and "lovelace" not in room.slug


# ---- the invariant ------------------------------------------------------

def test_owner_always_enters_their_own_room(present):
    u = member()
    room = room_for(u)
    present["live"] = False
    assert personal.can_enter_personal(room, u) is True


def test_invited_user_waits_until_the_owner_is_present(present):
    owner, guest = member(), member("invited@example.com")
    room = room_for(owner)
    RoomInvitation.objects.create(
        personal_room=room, invited_user=guest, expires_at=personal.new_expiry(),
    )
    present["live"] = False
    assert personal.can_enter_personal(room, guest) is False
    present["live"] = True
    assert personal.can_enter_personal(room, guest) is True


def test_uninvited_member_is_refused_even_when_the_owner_is_present(present):
    room = room_for(member())
    present["live"] = True
    assert personal.can_enter_personal(room, member("stranger@example.com")) is False


def test_guest_invitation_waits_for_the_owner_too(present):
    room = room_for(member())
    inv = RoomInvitation.objects.create(
        personal_room=room, token="tok-abc", guest_name="Applicant",
        expires_at=personal.new_expiry(),
    )
    present["live"] = False
    assert personal.can_enter_personal(room, None, invitation=inv) is False
    present["live"] = True
    assert personal.can_enter_personal(room, None, invitation=inv) is True


def test_an_unprovisioned_room_has_no_one_in_it():
    """No DailyRoom row means presence can't be read — and must read as absent,
    not as an unguarded room."""
    room = personal.personal_room_for(member(), create=True)
    assert personal.owner_present(room) is False


# ---- the site-technical exception --------------------------------------

@pytest.mark.parametrize("role", [StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER])
def test_site_technical_roles_are_refused_a_personal_room(present, role):
    """They enter and moderate every other meeting on the site. A personal room
    is private even from staff, the promise task #360 made for private channels.
    """
    room = room_for(member())
    tech = member("tech@example.com")
    grant(tech, role)
    present["live"] = True
    assert personal.can_enter_personal(room, tech) is False


# ---- invitations --------------------------------------------------------

def test_expired_and_revoked_invitations_are_refused(present):
    owner, invited = member(), member("invited@example.com")
    room = room_for(owner)
    present["live"] = True

    expired = RoomInvitation.objects.create(
        personal_room=room, invited_user=invited,
        expires_at=timezone.now() - _dt.timedelta(minutes=1),
    )
    assert personal.can_enter_personal(room, invited) is False
    expired.delete()

    live = RoomInvitation.objects.create(
        personal_room=room, invited_user=invited, expires_at=personal.new_expiry(),
    )
    assert personal.can_enter_personal(room, invited) is True
    live.revoke()
    assert personal.can_enter_personal(room, invited) is False


def test_guest_lookup_ignores_dead_tokens():
    room = room_for(member())
    RoomInvitation.objects.create(
        personal_room=room, token="dead", guest_name="X",
        expires_at=timezone.now() - _dt.timedelta(seconds=1),
    )
    assert personal.guest_invitation("dead") is None
    assert personal.guest_invitation("") is None


def test_an_invitation_is_reusable():
    """Not single-use: office hours and a rescheduled interview both want the
    same link twice, and link-scanners pre-click these."""
    room = room_for(member())
    inv = RoomInvitation.objects.create(
        personal_room=room, token="tok", guest_name="X", expires_at=personal.new_expiry(),
    )
    inv.touch()
    assert personal.guest_invitation("tok").pk == inv.pk


def test_an_invitation_is_one_kind_or_the_other():
    from django.db.utils import IntegrityError

    room = room_for(member())
    with pytest.raises(IntegrityError):
        RoomInvitation.objects.create(
            personal_room=room, invited_user=member("both@example.com"), token="t",
            expires_at=personal.new_expiry(),
        )


# ---- office hours -------------------------------------------------------

def test_posted_hours_admit_members_appointment_does_not(present):
    owner = member()
    room = room_for(owner)
    walk_in = member("student@example.com")
    present["live"] = True

    room.office_hours = PersonalRoom.OfficeHours.APPOINTMENT
    room.hours_note = "Write to me"
    room.save()
    assert room.advertises_hours is True
    assert personal.can_enter_personal(room, walk_in) is False

    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = "Thursdays 3-4pm Pacific"
    room.save()
    assert personal.can_enter_personal(room, walk_in) is True


def test_posted_hours_do_not_admit_a_non_member(present):
    """An offering's roster can include guests (task #566); the hours are shown
    to them, the door is not opened to them."""
    room = room_for(member())
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = "Thursdays"
    room.save()
    present["live"] = True
    assert personal.can_enter_personal(room, non_member()) is False


def test_posted_hours_still_wait_for_the_owner(present):
    room = room_for(member())
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = "Thursdays"
    room.save()
    present["live"] = False
    assert personal.can_enter_personal(room, member("student@example.com")) is False


def test_hours_with_no_note_are_not_advertised():
    room = personal.personal_room_for(member(), create=True)
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.save()
    assert room.advertises_hours is False
    assert personal.hours_for(room.user) is None


# ---- the room's Daily config -------------------------------------------

@daily_on
def test_recording_is_off_by_default_in_the_room_config():
    from video.services import _desired_properties, _room_name

    room = personal.personal_room_for(member(), create=True)
    assert _desired_properties(room)["enable_recording"] is False
    assert _room_name(room) == f"lsp-{room.slug}"

    room.recording_mode = PersonalRoom.RecordingMode.ON_DEMAND
    assert _desired_properties(room)["enable_recording"] == "cloud"


# ---- recordings ---------------------------------------------------------

def test_a_personal_recording_belongs_to_its_member_and_not_to_site_staff():
    from video.models import Recording

    owner = member()
    room = room_for(owner)
    tech = member("tech2@example.com")
    grant(tech, StaffRole.WEB_COORDINATOR)

    rec = Recording.objects.create(
        daily_recording_id="r1", room=room.video_room,
        status=Recording.Status.READY,
    )
    assert rec.is_personal is True
    assert rec.can_manage(owner) is True
    assert rec.can_manage(tech) is False
    # OWNERS by default, and the member is the only one it means.
    assert rec.content_visible_to(owner) is True
    assert rec.content_visible_to(tech) is False
    assert rec.content_visible_to(member("nobody@example.com")) is False


def test_a_dead_invitation_handed_in_directly_still_does_not_admit(present):
    """The access primitive re-checks a caller-supplied invitation rather than
    trusting it, so a caller that forgot to filter ``live()`` can't subvert it."""
    room = room_for(member())
    inv = RoomInvitation.objects.create(
        personal_room=room, token="tok-dead", guest_name="X", expires_at=personal.new_expiry(),
    )
    present["live"] = True
    assert personal.can_enter_personal(room, None, invitation=inv) is True
    inv.revoke()
    assert personal.can_enter_personal(room, None, invitation=inv) is False


# ---- the waiting room ---------------------------------------------------

@daily_on
def test_waiting_room_is_off_by_default_and_opts_the_room_in():
    """``enable_knocking`` is off for every group room and stays that way; only
    a personal room can carry it, because only it has the attribute."""
    from video.services import _desired_properties

    room = personal.personal_room_for(member(), create=True)
    assert room.waiting_room is False
    assert _desired_properties(room)["enable_knocking"] is False

    room.waiting_room = True
    assert _desired_properties(room)["enable_knocking"] is True


@daily_on
def test_a_group_room_never_knocks():
    from video.services import _desired_properties
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(name="A cartel", slug="a-cartel",
                                  kind=Workgroup.Kind.CARTEL)
    assert _desired_properties(wg)["enable_knocking"] is False


@daily_on
def test_the_token_carries_knocking_for_everyone_but_the_owner(monkeypatch):
    """A token normally *bypasses* knocking, so the room property alone would be
    inert here — every join on this site is token-minted."""
    minted = []
    monkeypatch.setattr(
        "video.daily.create_meeting_token",
        lambda **kw: minted.append(kw) or "tok",
    )
    monkeypatch.setattr(
        "video.daily.get_room",
        lambda name: {"url": f"https://lsp.daily.co/{name}", "config": {}},
    )
    monkeypatch.setattr("video.daily.update_room", lambda name, props: None)

    owner = member()
    room = room_for(owner)
    room.waiting_room = True
    room.save()

    class _Req:
        user = owner

    personal.room_context(_Req(), room, is_owner=True)
    assert minted[-1]["knocking"] is False

    personal.room_context(_Req(), room, is_owner=False)
    assert minted[-1]["knocking"] is True

    personal.room_context(_Req(), room, is_owner=False, guest_name="Jane")
    assert minted[-1]["knocking"] is True
    assert minted[-1]["user_name"] == "Jane"


# ---- posted hours admit the class, members or not -----------------------

def _seminar_led_by(teacher, slug="sem-roster"):
    from datetime import date

    from events.models import Event

    event = Event.objects.create(
        title="Seminar on the Letter", slug=slug, event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    wg = event.ensure_workgroup()
    event.add_faculty(teacher)
    return event, wg


def _post_hours(room):
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = "Thursdays 3-4pm Pacific"
    room.save()
    return room


def test_a_non_member_on_the_roster_walks_in_during_posted_hours(present):
    """The case that made re-inviting a chore: an Auditor or Student registered
    for the seminar is shown the hours, so the door has to open for them."""
    from registrations.models import Registration

    from .factories import register

    teacher = member("teacher@example.com")
    event, _wg = _seminar_led_by(teacher)
    student = non_member("auditor@example.com")
    register(student, event, status=Registration.Status.PAID)

    room = _post_hours(room_for(teacher))
    present["live"] = True
    assert personal.can_enter_personal(room, student) is True


def test_the_roster_rule_needs_posted_hours(present):
    from registrations.models import Registration

    from .factories import register

    teacher = member("teacher2@example.com")
    event, _wg = _seminar_led_by(teacher, slug="sem-appt")
    student = non_member("auditor2@example.com")
    register(student, event, status=Registration.Status.PAID)

    room = room_for(teacher)
    present["live"] = True
    assert personal.can_enter_personal(room, student) is False  # office hours off

    room.office_hours = PersonalRoom.OfficeHours.APPOINTMENT
    room.hours_note = "Write to me"
    room.save()
    assert personal.can_enter_personal(room, student) is False


def test_a_non_member_off_the_roster_still_stays_out(present):
    teacher = member("teacher3@example.com")
    _seminar_led_by(teacher, slug="sem-out")
    room = _post_hours(room_for(teacher))
    present["live"] = True
    assert personal.can_enter_personal(room, non_member("stranger@example.com")) is False


def test_only_offerings_you_lead_count(present):
    """Being on someone's roster admits you to *their* room, not to the room of
    another member who happens to be on it too."""
    from registrations.models import Registration

    from .factories import register

    teacher = member("teacher4@example.com")
    bystander = member("bystander@example.com")
    event, _wg = _seminar_led_by(teacher, slug="sem-lead")
    student = non_member("auditor4@example.com")
    register(student, event, status=Registration.Status.PAID)
    register(bystander, event, status=Registration.Status.PAID)

    room = _post_hours(room_for(bystander))
    present["live"] = True
    assert personal.can_enter_personal(room, student) is False


def test_the_roster_rule_still_waits_for_the_owner(present):
    from registrations.models import Registration

    from .factories import register

    teacher = member("teacher5@example.com")
    event, _wg = _seminar_led_by(teacher, slug="sem-wait")
    student = non_member("auditor5@example.com")
    register(student, event, status=Registration.Status.PAID)

    room = _post_hours(room_for(teacher))
    present["live"] = False
    assert personal.can_enter_personal(room, student) is False


# ---- an account-bound invitation does not expire ------------------------

def test_an_account_bound_invitation_has_no_expiry(present):
    owner, invited = member(), member("invited@example.com")
    room = room_for(owner)
    inv = RoomInvitation.objects.create(personal_room=room, invited_user=invited, expires_at=None)
    present["live"] = True

    assert inv.expires_at is None
    assert inv.is_expired() is False
    assert inv.is_live is True
    assert personal.can_enter_personal(room, invited) is True

    # Revoking is how it ends.
    inv.revoke()
    assert personal.can_enter_personal(room, invited) is False


def test_live_finds_never_expiring_invitations():
    room = room_for(member())
    RoomInvitation.objects.create(personal_room=room, invited_user=member("i@example.com"),
                                  expires_at=None)
    assert room.invitations.live().count() == 1
