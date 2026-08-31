"""The entrances to a group's room for someone who is not in the group (task #694)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from video.models import RoomInvitation

from .factories import daily_on, seminar, special_event, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
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
    minted = {}

    def _get_room(name):
        return {"url": f"https://lsp.daily.co/{name}", "config": {}}

    def _token(*, room_name, user_name, is_owner, exp, **kwargs):
        minted.update(room=room_name, name=user_name, owner=is_owner, extra=kwargs)
        return "tok"

    monkeypatch.setattr("video.daily.get_room", _get_room)
    monkeypatch.setattr("video.daily.update_room", lambda name, props: _get_room(name))
    monkeypatch.setattr("video.daily.create_room", lambda name, properties=None: _get_room(name))
    monkeypatch.setattr("video.daily.create_meeting_token", _token)
    return minted


def group():
    return seminar().ensure_workgroup()


def led_group():
    """A seminar with a faculty lead, which is what ``is_owner`` reads."""
    event = seminar()
    wg = event.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    event.add_faculty(lead)
    return wg, lead


# ---- an invited account holder ------------------------------------------

def test_an_invited_account_holder_uses_the_ordinary_room_url(client, stub_daily, present):
    wg = group()
    guest = user("guest@example.com")
    RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    client.force_login(guest)
    url = reverse("video:workgroup_room", args=[wg.slug])

    waiting = client.get(url)
    assert waiting.status_code == 200
    assert b"has not started" in waiting.content

    present["live"] = True
    assert client.get(url).status_code == 200
    assert stub_daily["owner"] is False


def test_an_uninvited_stranger_still_gets_403(client, stub_daily, present):
    wg = group()
    client.force_login(user("stranger@example.com"))
    present["live"] = True
    assert client.get(reverse("video:workgroup_room", args=[wg.slug])).status_code == 403


def test_a_revoked_invitation_closes_the_ordinary_room_url(client, stub_daily, present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    invitation.revoke()
    present["live"] = True
    client.force_login(guest)
    assert client.get(reverse("video:workgroup_room", args=[wg.slug])).status_code == 403


# ---- an anonymous guest --------------------------------------------------

def test_the_guest_doorstep_mints_nothing_on_get(client, present, monkeypatch):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    present["live"] = True

    def _boom(*a, **k):
        raise AssertionError("a GET must not mint a token")

    monkeypatch.setattr("video.daily.create_meeting_token", _boom)
    assert client.get(reverse("video:guest_room", args=[invitation.token])).status_code == 200


def test_a_guest_joins_a_group_room_by_posting_a_name(client, stub_daily, present):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    present["live"] = True
    resp = client.post(
        reverse("video:guest_room", args=[invitation.token]), {"display_name": "Jane Doe"}
    )
    assert resp.status_code == 200
    assert stub_daily["name"] == "Jane Doe"
    assert stub_daily["owner"] is False


def test_a_guest_arriving_early_is_held_at_the_doorstep(client, stub_daily, present):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    resp = client.post(
        reverse("video:guest_room", args=[invitation.token]), {"display_name": "Jane Doe"}
    )
    assert resp.status_code == 200
    assert b"has not started" in resp.content
    assert "name" not in stub_daily


def test_an_unknown_token_is_a_404(client):
    assert client.get(reverse("video:guest_room", args=["nonsense"])).status_code == 404


def test_a_guest_at_a_spotlight_event_starts_muted(client, stub_daily, present):
    event = special_event()
    event.speaker_spotlight = True
    event.save(update_fields=["speaker_spotlight"])
    invitation = RoomInvitation.objects.create(
        event=event, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    present["live"] = True
    client.post(
        reverse("video:guest_room", args=[invitation.token]), {"display_name": "Jane Doe"}
    )
    assert stub_daily["extra"]["start_audio_off"] is True
    assert stub_daily["extra"]["start_video_off"] is True


# ---- presence -----------------------------------------------------------

def test_the_presence_endpoint_needs_the_token(client, present):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    assert client.get(reverse("video:guest_presence", args=["nonsense"])).status_code == 404
    assert client.get(
        reverse("video:guest_presence", args=[invitation.token])
    ).json() == {"live": False}


def test_an_invitees_presence_endpoint_is_theirs_alone(client, present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    url = reverse("video:invitation_presence", args=[invitation.pk])

    client.force_login(user("someone.else@example.com"))
    assert client.get(url).status_code == 404

    client.force_login(guest)
    assert client.get(url).json() == {"live": False}


# ---- inviting -----------------------------------------------------------

def test_only_a_lead_may_invite(client, stub_daily):
    wg, lead = led_group()
    plain = user("plain@example.com")
    wg.add_member(plain)
    url = reverse("video:workgroup_invite", args=[wg.slug])

    client.force_login(plain)
    assert client.post(url, {"others": "Jane Doe"}).status_code == 403
    assert not RoomInvitation.objects.filter(workgroup=wg).exists()

    client.force_login(lead)
    assert client.post(url, {"others": "Jane Doe"}).status_code == 302
    assert RoomInvitation.objects.filter(workgroup=wg).count() == 1


def test_the_web_coordinator_may_invite(client, stub_daily):
    from core.models import StaffRole

    wg = group()
    coordinator = user("wc@example.com")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"}
    )
    role.holders.add(coordinator)
    client.force_login(coordinator)
    assert client.post(
        reverse("video:workgroup_invite", args=[wg.slug]), {"others": "Jane Doe"}
    ).status_code == 302
    assert RoomInvitation.objects.filter(workgroup=wg).count() == 1


def test_an_offering_event_has_no_invite_endpoint_of_its_own(client, stub_daily):
    """It meets in its workgroup's room; inviting there would bind the invitation
    to a room the event does not own."""
    event = seminar()
    event.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    event.add_faculty(lead)
    client.force_login(lead)
    resp = client.post(
        reverse("video:event_invite", args=[event.slug]), {"others": "Jane Doe"}
    )
    assert resp.status_code == 404


def test_a_one_off_event_invites_against_itself(client, stub_daily):
    from events.permissions import can_edit_event

    event = special_event()
    host = user("host@example.com", is_faculty=True)
    event.add_faculty(host)
    assert can_edit_event(host, event)
    client.force_login(host)
    assert client.post(
        reverse("video:event_invite", args=[event.slug]), {"others": "Jane Doe"}
    ).status_code == 302
    assert RoomInvitation.objects.filter(event=event).count() == 1


def test_revoke_is_refused_to_someone_else(client):
    wg = group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    client.force_login(user("nobody@example.com"))
    assert client.post(
        reverse("video:invitation_revoke", args=[invitation.pk])
    ).status_code == 404
    invitation.refresh_from_db()
    assert invitation.revoked_at is None


def test_a_lead_revokes(client):
    wg, lead = led_group()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    client.force_login(lead)
    assert client.post(
        reverse("video:invitation_revoke", args=[invitation.pk])
    ).status_code == 302
    invitation.refresh_from_db()
    assert invitation.revoked_at is not None


# ---- telling the person -------------------------------------------------

def test_a_guest_invitation_emails_the_link_and_names_the_group(mailoutbox):
    from video import notifications_invitations as notify
    from video.forms_invitations import InvitationForm, Recipient
    from video.invitations import target_for

    wg = group()
    lead = user("lead@example.com")
    form = InvitationForm(target=target_for(wg))
    invitation = form.build(
        Recipient(user=None, name="Jane Doe", email="jane@example.com"), by=lead
    )
    notify.send_invitation(invitation)
    assert len(mailoutbox) == 1
    assert wg.name in mailoutbox[0].body
    assert invitation.token in mailoutbox[0].body
    assert mailoutbox[0].reply_to == [lead.email]


def test_a_group_guest_email_says_nothing_about_expiry(mailoutbox):
    from video import notifications_invitations as notify
    from video.forms_invitations import InvitationForm, Recipient
    from video.invitations import target_for

    form = InvitationForm(target=target_for(group()))
    invitation = form.build(
        Recipient(user=None, name="Jane Doe", email="jane@example.com"),
        by=user("lead@example.com"),
    )
    notify.send_invitation(invitation)
    assert "The link works until" not in mailoutbox[0].body


def test_an_account_holder_gets_a_bell_row_pointing_at_the_room():
    from notifications.models import Notification
    from video import notifications_invitations as notify

    wg = group()
    guest = user("guest@example.com")
    lead = user("lead@example.com")
    invitation = RoomInvitation.objects.create(
        workgroup=wg, invited_user=guest, invited_by=lead
    )
    notify.send_invitation(invitation)
    row = Notification.objects.filter(recipient=guest).first()
    assert row is not None
    assert wg.name in row.title
    assert wg.slug in row.url


# ---- the panel ----------------------------------------------------------

def test_the_meet_tab_offers_the_panel_to_a_lead_only(client, stub_daily, present):
    wg, lead = led_group()
    plain = user("plain@example.com")
    wg.add_member(plain)
    url = wg.get_absolute_url() + "?tab=meet"

    client.force_login(plain)
    assert b"Who else can join" not in client.get(url).content

    client.force_login(lead)
    assert b"Who else can join" in client.get(url).content


def test_a_one_off_events_faculty_tools_offer_the_panel(client, stub_daily):
    event = special_event()
    host = user("host@example.com", is_faculty=True)
    event.add_faculty(host)
    client.force_login(host)
    resp = client.get(reverse("events:detail", args=[event.slug]) + "?view=faculty")
    assert b"Who else can join" in resp.content
    assert f"/events/{event.slug}/room/invite/".encode() in resp.content


def test_an_offering_page_offers_no_event_invite_form(client, stub_daily):
    """It meets in its workgroup's room; the panel belongs on the Meet tab."""
    event = seminar()
    event.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    event.add_faculty(lead)
    client.force_login(lead)
    resp = client.get(
        reverse("events:detail", args=[event.slug]) + "?view=faculty", follow=True
    )
    assert f"/events/{event.slug}/room/invite/".encode() not in resp.content


def test_the_panel_lists_a_guest_link_to_copy(client, stub_daily, present):
    wg, lead = led_group()
    RoomInvitation.objects.create(
        workgroup=wg, token="copy-me-token", guest_name="Jane Doe", invited_by=lead
    )
    client.force_login(lead)
    resp = client.get(wg.get_absolute_url() + "?tab=meet")
    assert b"copy-me-token" in resp.content
    assert b"Jane Doe" in resp.content
