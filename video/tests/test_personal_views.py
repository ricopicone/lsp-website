"""The four entrances to a private meeting room, and the tab that manages it
(task #687)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from video import services_personal as personal
from video.models import PersonalRoom, RoomInvitation

from .factories import daily_on
from .test_personal_rooms import grant, member, non_member, room_for

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
    """``daily_on`` is an ``override_settings`` object, so it can't ride in
    ``pytestmark``; every test here needs the feature on."""
    with daily_on:
        yield


@pytest.fixture
def present(monkeypatch):
    state = {"live": False}
    monkeypatch.setattr(
        "video.services.room_participant_count", lambda room: 1 if state["live"] else 0
    )
    return state


@pytest.fixture
def stub_daily(monkeypatch):
    """Keep provisioning and token minting off the network."""
    minted = {}

    def _get_room(name):
        return {"url": f"https://lsp.daily.co/{name}", "config": {}}

    def _token(*, room_name, user_name, is_owner, exp, **kwargs):
        minted.update(room=room_name, name=user_name, owner=is_owner)
        return "tok"

    monkeypatch.setattr("video.daily.get_room", _get_room)
    monkeypatch.setattr("video.daily.update_room", lambda name, props: _get_room(name))
    monkeypatch.setattr("video.daily.create_room", lambda name, properties=None: _get_room(name))
    monkeypatch.setattr("video.daily.create_meeting_token", _token)
    return minted


# ---- the member's own room ---------------------------------------------

def test_my_room_creates_the_room_and_joins_as_owner(client, stub_daily, present):
    u = member()
    client.force_login(u)
    resp = client.get(reverse("video:my_room"))
    assert resp.status_code == 200
    assert PersonalRoom.objects.filter(user=u).exists()
    assert stub_daily["owner"] is True


def test_a_non_member_has_no_room(client, stub_daily):
    client.force_login(non_member())
    assert client.get(reverse("video:my_room")).status_code == 404


def test_the_room_tab_is_members_only():
    from formation.tabs import available_tabs

    assert "room" in dict(available_tabs(member()))
    assert "room" not in dict(available_tabs(non_member()))


# ---- an invited account holder ------------------------------------------

def test_invited_user_is_held_at_the_door_then_admitted(client, stub_daily, present):
    owner = member()
    room = room_for(owner)
    invited = member("invited@example.com")
    RoomInvitation.objects.create(
        personal_room=room, invited_user=invited, expires_at=personal.new_expiry(),
    )
    client.force_login(invited)
    url = reverse("video:personal_room", args=[room.slug])

    present["live"] = False
    waiting = client.get(url)
    assert waiting.status_code == 200
    assert b"has not started the meeting yet" in waiting.content

    present["live"] = True
    joined = client.get(url)
    assert joined.status_code == 200
    assert stub_daily["owner"] is False


def test_uninvited_member_is_refused_with_403(client, stub_daily, present):
    room = room_for(member())
    client.force_login(member("stranger@example.com"))
    present["live"] = True
    resp = client.get(reverse("video:personal_room", args=[room.slug]))
    assert resp.status_code == 403


def test_site_technical_role_is_refused_the_room_page(client, stub_daily, present):
    from core.models import StaffRole

    room = room_for(member())
    tech = member("tech@example.com")
    grant(tech, StaffRole.WEB_COORDINATOR)
    client.force_login(tech)
    present["live"] = True
    assert client.get(reverse("video:personal_room", args=[room.slug])).status_code == 403


def test_the_owner_visiting_their_own_slug_is_sent_to_my_room(client, stub_daily):
    owner = member()
    room = room_for(owner)
    client.force_login(owner)
    resp = client.get(reverse("video:personal_room", args=[room.slug]))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("video:my_room")


# ---- the guest doorstep --------------------------------------------------

def guest_invite(room, **kwargs):
    return RoomInvitation.objects.create(
        personal_room=room, token="secret-token", guest_name="Jane Doe",
        expires_at=personal.new_expiry(), **kwargs
    )


def test_guest_get_mints_nothing(client, stub_daily, present):
    """A link-scanner pre-clicking the emailed link must not land in the room."""
    room = room_for(member())
    guest_invite(room)
    present["live"] = True
    resp = client.get(reverse("video:guest_room", args=["secret-token"]))
    assert resp.status_code == 200
    assert stub_daily == {}
    assert b"Jane Doe" in resp.content


def test_guest_post_joins_under_the_name_they_gave(client, stub_daily, present):
    room = room_for(member())
    guest_invite(room)
    present["live"] = True
    resp = client.post(
        reverse("video:guest_room", args=["secret-token"]),
        {"display_name": "Jane D."},
    )
    assert resp.status_code == 200
    assert stub_daily["name"] == "Jane D."
    assert stub_daily["owner"] is False


def test_guest_post_waits_when_the_host_is_absent(client, stub_daily, present):
    room = room_for(member())
    guest_invite(room)
    present["live"] = False
    resp = client.post(
        reverse("video:guest_room", args=["secret-token"]),
        {"display_name": "Jane D."},
    )
    assert resp.status_code == 200
    assert b"has not started the meeting yet" in resp.content
    assert stub_daily == {}


def test_a_revoked_guest_link_is_gone(client, stub_daily, present):
    room = room_for(member())
    guest_invite(room).revoke()
    present["live"] = True
    assert client.get(reverse("video:guest_room", args=["secret-token"])).status_code == 404


def test_presence_endpoint_says_only_whether_the_host_is_there(client, present):
    room = room_for(member())
    present["live"] = True
    resp = client.get(reverse("video:room_presence", args=[room.slug]))
    assert resp.json() == {"live": True}


# ---- managing ------------------------------------------------------------

def test_inviting_a_member_notifies_them(client, stub_daily):
    from notifications.models import Notification

    owner, invited = member(), member("invited@example.com")
    client.force_login(owner)
    resp = client.post(reverse("video:room_invite"), {"members": [invited.pk]})
    assert resp.status_code == 302
    invitation = RoomInvitation.objects.get()
    assert invitation.invited_user == invited
    assert invitation.token is None
    assert Notification.objects.filter(recipient=invited).exists()


def test_inviting_an_unknown_email_makes_a_guest_link(client, stub_daily, mailoutbox):
    owner = member()
    client.force_login(owner)
    client.post(reverse("video:room_invite"), {
        "others": "A Stranger <stranger@example.com>", "send_email": "on",
    })
    invitation = RoomInvitation.objects.get()
    assert invitation.is_guest
    assert invitation.guest_name == "A Stranger"
    assert len(mailoutbox) == 1
    assert invitation.token in mailoutbox[0].body


def test_inviting_a_known_email_binds_to_that_account(client, stub_daily):
    """An applicant already has an account, so they sign in rather than
    following a secret link."""
    owner = member()
    applicant = non_member("applicant@example.com")
    client.force_login(owner)
    client.post(reverse("video:room_invite"), {"others": f"App <{applicant.email}>"})
    invitation = RoomInvitation.objects.get()
    assert invitation.invited_user == applicant
    assert invitation.token is None


def test_revoking_is_scoped_to_your_own_room(client, stub_daily):
    room = room_for(member())
    invitation = guest_invite(room)
    client.force_login(member("someone.else@example.com"))
    resp = client.post(reverse("video:invitation_revoke", args=[invitation.pk]))
    assert resp.status_code == 404
    invitation.refresh_from_db()
    assert invitation.revoked_at is None


def test_office_hours_need_a_note(client, stub_daily):
    owner = member()
    client.force_login(owner)
    client.post(reverse("video:room_settings"), {
        "office_hours": PersonalRoom.OfficeHours.POSTED,
        "recording_mode": PersonalRoom.RecordingMode.OFF,
        "hours_note": "",
    })
    room = PersonalRoom.objects.get(user=owner)
    assert room.office_hours == PersonalRoom.OfficeHours.OFF


def test_settings_save(client, stub_daily):
    owner = member()
    client.force_login(owner)
    client.post(reverse("video:room_settings"), {
        "office_hours": PersonalRoom.OfficeHours.POSTED,
        "recording_mode": PersonalRoom.RecordingMode.ON_DEMAND,
        "hours_note": "Thursdays 3-4pm Pacific",
    })
    room = PersonalRoom.objects.get(user=owner)
    assert room.admits_members is True
    assert room.recording_mode == PersonalRoom.RecordingMode.ON_DEMAND


# ---- the directory surface ----------------------------------------------

def test_office_hours_are_members_only_on_the_directory(client, stub_daily):
    owner = member(first="Ada", last="Lovelace")
    owner.profile.public = True
    owner.profile.save()
    room = personal.personal_room_for(owner, create=True)
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = "Thursdays 3-4pm Pacific"
    room.save()
    url = reverse("directory_detail", args=[owner.profile.directory_slug])

    anon = client.get(url)
    assert b"Thursdays 3-4pm Pacific" not in anon.content

    client.force_login(member("viewer@example.com"))
    assert b"Thursdays 3-4pm Pacific" in client.get(url).content


# ---- the Workspace surface ----------------------------------------------

def _seminar_with_faculty(teacher):
    from datetime import date

    from events.models import Event

    event = Event.objects.create(
        title="Seminar on the Letter", slug="sem-hours",
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=Event.Status.OPEN,
    )
    wg = event.ensure_workgroup()
    event.add_faculty(teacher)
    return event, wg


def _post_hours(user, note="Thursdays 3-4pm Pacific"):
    room = personal.personal_room_for(user, create=True)
    room.office_hours = PersonalRoom.OfficeHours.POSTED
    room.hours_note = note
    room.save()
    return room


def test_offering_hours_finds_whoever_runs_the_offering():
    teacher = member("teacher@example.com", first="Tess", last="Teacher")
    event, _wg = _seminar_with_faculty(teacher)
    assert personal.offering_hours(event) == []
    _post_hours(teacher)
    rows = personal.offering_hours(event)
    assert [u.pk for u, _room in rows] == [teacher.pk]


def test_workspace_shows_the_faculty_office_hours_to_the_roster(client, stub_daily):
    teacher = member("teacher2@example.com", first="Tess", last="Teacher")
    event, wg = _seminar_with_faculty(teacher)
    _post_hours(teacher)
    client.force_login(teacher)
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Thursdays 3-4pm Pacific" in resp.content


# ---- a personal recording stays private ---------------------------------

def test_a_personal_recording_cannot_be_made_public_by_a_hand_rolled_post(client):
    from video.models import Recording

    owner = member()
    room = room_for(owner)
    rec = Recording.objects.create(
        daily_recording_id="rp1", room=room.video_room, status=Recording.Status.READY,
    )
    client.force_login(owner)
    resp = client.post(reverse("video:recording_availability", args=[rec.pk]), {
        "listing_visibility": Recording.Visibility.PUBLIC,
        "content_visibility": Recording.Visibility.PUBLIC,
    })
    assert resp.status_code == 403
    rec.refresh_from_db()
    assert rec.content_visibility == Recording.Visibility.OWNERS


# ---- inviting: the email is optional -------------------------------------

def test_a_name_alone_makes_a_guest_link_and_sends_nothing(client, stub_daily, mailoutbox):
    """The email only ever sends the invitation; it gates nothing, since a guest
    link admits whoever opens it."""
    client.force_login(member())
    resp = client.post(reverse("video:room_invite"), {"others": "A Stranger"})
    assert resp.status_code == 302
    invitation = RoomInvitation.objects.get()
    assert invitation.is_guest
    assert invitation.guest_name == "A Stranger"
    assert invitation.guest_email == ""
    assert mailoutbox == []


def test_an_email_with_no_name_still_binds_to_a_known_account(client, stub_daily):
    owner = member()
    applicant = non_member("applicant2@example.com")
    client.force_login(owner)
    client.post(reverse("video:room_invite"), {"others": applicant.email})
    assert RoomInvitation.objects.get().invited_user == applicant


def test_an_unknown_email_with_no_name_asks_for_one(client, stub_daily):
    client.force_login(member())
    client.post(reverse("video:room_invite"), {"others": "nobody@example.com"})
    assert not RoomInvitation.objects.exists()


def test_nothing_at_all_is_refused(client, stub_daily):
    client.force_login(member())
    client.post(reverse("video:room_invite"), {"others": "   "})
    assert not RoomInvitation.objects.exists()


def test_the_member_picker_lists_names_not_addresses(client, stub_daily):
    from video.forms_invitations import InvitationForm
    from video.invitations import target_for

    owner = member()
    member("Pickable@example.com", first="Ada", last="Lovelace")
    room = personal.personal_room_for(owner, create=True)
    field = InvitationForm(target=target_for(room)).fields["members"]
    labels = [str(label) for _value, label in field.choices]
    assert "Ada Lovelace" in labels
    assert not any("@" in label for label in labels if label != "Choose a member…")


def test_several_people_are_invited_at_once(client, stub_daily):
    owner = member()
    a = member("a@example.com", first="Ann", last="Alpha")
    b = member("b@example.com", first="Ben", last="Beta")
    client.force_login(owner)
    client.post(reverse("video:room_invite"), {
        "members": [a.pk, b.pk],
        "others": "Jane Doe <jane@example.com>\nJust A Name\n",
    })
    invitations = RoomInvitation.objects.all()
    assert invitations.count() == 4
    assert {i.invited_user for i in invitations if i.invited_user} == {a, b}
    guests = {(i.guest_name, i.guest_email) for i in invitations if i.is_guest}
    assert guests == {("Jane Doe", "jane@example.com"), ("Just A Name", "")}


def test_the_same_person_ticked_and_typed_is_one_invitation(client, stub_daily):
    owner = member()
    a = member("a@example.com", first="Ann", last="Alpha")
    client.force_login(owner)
    client.post(reverse("video:room_invite"), {
        "members": [a.pk], "others": f"Ann Alpha <{a.email}>",
    })
    assert RoomInvitation.objects.count() == 1


def test_personas_are_not_offered(client, stub_daily):
    from video.forms_invitations import InvitationForm
    from video.invitations import target_for

    owner = member()
    persona = member("persona@example.com", first="Persona", last="Chair")
    persona.profile.is_persona = True
    persona.profile.save()
    room = personal.personal_room_for(owner, create=True)
    field = InvitationForm(target=target_for(room)).fields["members"]
    labels = [str(label) for _v, label in field.choices]
    assert "Persona Chair" not in labels


def test_a_malformed_address_is_reported_not_swallowed(client, stub_daily):
    client.force_login(member())
    client.post(reverse("video:room_invite"), {"others": "Jane <not-an-address>"})
    assert not RoomInvitation.objects.exists()
