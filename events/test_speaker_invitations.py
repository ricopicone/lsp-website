"""External-speaker invitation token (task #463)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from committees.models import Committee
from events.models import Event, Speaker, SpeakerInvitation

pytestmark = pytest.mark.django_db


def _speaker_with_user(email="d@x.test"):
    u = User.objects.create_user(email=email)
    s = Speaker.objects.create(name="Derek Hook", slug="dh-inv", email=email, user=u)
    return s, u


def test_invitation_is_valid_until_expiry_and_use():
    s, u = _speaker_with_user()
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() + timedelta(days=10)
    )
    assert inv.token
    assert inv.is_valid is True
    inv.consume()
    assert inv.used_at is not None
    assert inv.is_valid is False


def test_invitation_expired_is_invalid():
    s, u = _speaker_with_user("e@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert inv.is_expired() is True
    assert inv.is_valid is False


def test_refresh_issues_new_token_and_clears_use():
    s, u = _speaker_with_user("f@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(days=1)
    )
    old = inv.token
    inv.consume()
    inv.refresh()
    assert inv.token != old
    assert inv.used_at is None
    assert inv.is_valid is True


def _special_event(slug="inv-talk"):
    return Event.objects.create(
        title="Working with Masochism", slug=slug,
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 6), end_date=date(2030, 9, 6),
        published=True, status=Event.Status.OPEN,
    )


def test_invitation_expires_the_day_after_the_event():
    # Not a fixed 30 days: an invitation must never lapse before the speaker
    # needs it, however far out the event is.
    from events.speaker_invitations import invitation_expiry

    e = _special_event("exp-day-after")  # 2030-09-06
    exp = invitation_expiry(e)
    assert timezone.localtime(exp).date() == date(2030, 9, 7)


def test_invitation_outlives_an_event_further_out_than_the_old_30_day_ttl():
    # The regression this fixes: Derek Hook was invited 2026-07-27 for an event
    # on 2026-09-06, and the 30-day TTL expired 2026-08-26 — eleven days early.
    from events.speaker_invitations import invitation_expiry

    e = _special_event("exp-regression")
    exp = invitation_expiry(e)
    assert exp > timezone.now() + SpeakerInvitation.DEFAULT_TTL


def test_invitation_prefers_the_last_session_over_end_date():
    from events.models import Session
    from events.speaker_invitations import invitation_expiry

    e = _special_event("exp-sessions")
    start = timezone.now() + timedelta(days=100)
    Session.objects.create(
        event=e, sequence=1, start_at=start, end_at=start + timedelta(hours=3)
    )
    exp = invitation_expiry(e)
    expected = (timezone.localtime(start).date() + timedelta(days=1))
    assert timezone.localtime(exp).date() == expected


def test_invitation_for_an_imminent_event_still_gets_a_usable_window():
    # "Day after the event" alone would hand someone invited the morning of a
    # same-day event a window of hours. Floored so it stays usable.
    from events.speaker_invitations import MIN_INVITATION_WINDOW, invitation_expiry

    e = Event.objects.create(
        title="Tomorrow", slug="exp-imminent", event_type=Event.Type.SPECIAL_EVENT,
        start_date=timezone.localdate(), end_date=timezone.localdate(),
    )
    assert invitation_expiry(e) >= timezone.now() + MIN_INVITATION_WINDOW - timedelta(minutes=1)


def test_invitation_for_a_past_event_is_not_born_dead():
    # Inviting someone after their event (recording access, a re-run) must not
    # mint an already-expired token.
    from events.speaker_invitations import invitation_expiry

    e = Event.objects.create(
        title="Last year", slug="exp-past", event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2020, 1, 1), end_date=date(2020, 1, 1),
    )
    assert invitation_expiry(e) > timezone.now()


def test_invitation_falls_back_to_the_default_ttl_without_a_date():
    from events.speaker_invitations import invitation_expiry

    floor = timezone.now() + SpeakerInvitation.DEFAULT_TTL - timedelta(minutes=1)
    assert invitation_expiry(None) > floor


def test_send_invitation_applies_the_event_derived_expiry():
    from events.speaker_invitations import invitation_expiry, send_invitation

    e = _special_event("exp-send")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-exp", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="hello")
    assert timezone.localtime(inv.expires_at).date() == date(2030, 9, 7)
    assert inv.expires_at == invitation_expiry(e)


def test_resending_an_invitation_re_derives_the_expiry():
    # A resend must not quietly fall back to the 30-day default via refresh().
    from events.speaker_invitations import send_invitation

    e = _special_event("exp-resend")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-exp2", email="derek@x.test")
    e.speakers.add(s)
    send_invitation(s, e, message="first")
    inv = send_invitation(s, e, message="second")
    assert timezone.localtime(inv.expires_at).date() == date(2030, 9, 7)


def test_provision_login_creates_external_user():
    from events.speaker_invitations import provision_login
    s = Speaker.objects.create(name="Derek Hook", slug="dh-prov", email="derek@x.test")
    u = provision_login(s)
    s.refresh_from_db()
    assert s.user == u
    assert u.email == "derek@x.test"
    assert u.profile.role == Profile.Role.EXTERNAL
    assert u.profile.public is False
    assert u.has_usable_password() is False
    assert u.first_name == "Derek" and u.last_name == "Hook"


def test_provision_login_links_existing_user_not_duplicate():
    from events.speaker_invitations import provision_login
    existing = User.objects.create_user(email="dup@x.test", first_name="Dup")
    s = Speaker.objects.create(name="Dup Person", slug="dup-p", email="dup@x.test")
    u = provision_login(s)
    assert u == existing
    assert User.objects.filter(email="dup@x.test").count() == 1


def test_send_invitation_creates_token_and_sends_one_email():
    from events.speaker_invitations import send_invitation
    e = _special_event()
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="Looking forward to it.")
    assert inv.is_valid
    assert inv.user.email == "derek@x.test"
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert inv.token in body
    assert "Looking forward to it." in body
    assert mail.outbox[0].to == ["derek@x.test"]


def test_send_invitation_resend_refreshes_token():
    from events.speaker_invitations import send_invitation
    e = _special_event("inv-talk-2")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-resend", email="derek@x.test")
    e.speakers.add(s)
    inv1 = send_invitation(s, e, message="first")
    t1 = inv1.token
    inv2 = send_invitation(s, e, message="second")
    assert inv2.pk == inv1.pk
    assert inv2.token != t1
    assert len(mail.outbox) == 2


def _pc_user():
    u = User.objects.create_user(email="pc@x.test")
    Committee.objects.get_or_create(
        slug="programming-committee", defaults={"name": "Programming Committee"}
    )[0].add_member(u, start_date=date(2026, 1, 1))
    return u


def test_edit_page_shows_ready_to_invite_panel(client):
    e = _special_event("panel-1")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-panel", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(reverse("events:edit", args=[e.slug]))
    assert b"Ready to invite" in resp.content
    assert b"Derek Hook" in resp.content


def test_emailless_speaker_shows_add_email_affordance(client):
    e = _special_event("panel-2")
    s = Speaker.objects.create(name="No Email", slug="no-email")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(reverse("events:edit", args=[e.slug]))
    # The speaker is shown (not silently skipped) with a way to add an email.
    assert b"No Email" in resp.content
    assert b"No email on file" in resp.content
    assert b'name="email"' in resp.content
    assert b"Ready to invite" not in resp.content


def test_adding_email_then_sending_invites(client):
    e = _special_event("panel-2b")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-addmail")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"email": "derek@x.test", "message": "Please join us."}, follow=True,
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.email == "derek@x.test"
    assert s.user is not None
    assert len(mail.outbox) == 1


def test_invite_without_email_errors_and_does_not_send(client):
    e = _special_event("panel-2c")
    s = Speaker.objects.create(name="Derek", slug="dh-noemail2")
    e.speakers.add(s)
    client.force_login(_pc_user())
    client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "x"}, follow=True,
    )
    s.refresh_from_db()
    assert s.email == ""
    assert s.user is None
    assert len(mail.outbox) == 0


def test_invite_with_invalid_email_errors(client):
    e = _special_event("panel-2d")
    s = Speaker.objects.create(name="Derek", slug="dh-bademail")
    e.speakers.add(s)
    client.force_login(_pc_user())
    client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"email": "not-an-email", "message": "x"}, follow=True,
    )
    s.refresh_from_db()
    assert s.email == ""
    assert len(mail.outbox) == 0


def test_confirm_send_invites(client):
    e = _special_event("panel-3")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send2", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "Please join us."}, follow=True,
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.user is not None
    assert len(mail.outbox) == 1


def test_speaker_invite_forbidden_for_non_pc(client):
    e = _special_event("panel-4")
    s = Speaker.objects.create(name="Derek", slug="dh-forbid", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(User.objects.create_user(email="rando@x.test"))
    resp = client.post(
        reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "x"},
    )
    assert resp.status_code == 403
    s.refresh_from_db()
    assert s.user is None


def test_accept_sets_password_and_logs_in(client):
    from events.speaker_invitations import send_invitation
    e = _special_event("accept-1")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-accept", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="hi")
    url = reverse("events:speaker_invitation_accept", args=[inv.token])
    assert client.get(url).status_code == 200
    inv.refresh_from_db()
    assert inv.used_at is None
    resp = client.post(url, {"new_password1": "Sw0rdfish!42", "new_password2": "Sw0rdfish!42"})
    assert resp.status_code == 302
    assert resp.url == reverse("events:detail", args=[e.slug])
    inv.refresh_from_db()
    assert inv.used_at is not None
    inv.user.refresh_from_db()
    assert inv.user.has_usable_password() is True
    from video.services import can_enter_event
    assert can_enter_event(e, inv.user) is True


def test_accept_rejects_expired_token(client):
    from events.speaker_invitations import send_invitation
    e = _special_event("accept-2")
    s = Speaker.objects.create(name="Derek", slug="dh-exp", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="hi")
    inv.expires_at = timezone.now() - timedelta(minutes=1)
    inv.save(update_fields=["expires_at"])
    resp = client.get(reverse("events:speaker_invitation_accept", args=[inv.token]))
    assert resp.status_code == 410


def test_accept_rejects_unknown_token(client):
    resp = client.get(reverse("events:speaker_invitation_accept", args=["nope"]))
    assert resp.status_code == 410


def test_end_to_end_derek_scenario(client):
    """Mirror the real case: an external speaker with a comma in the name and no
    email, on a special event that also has a member-speaker. PC adds the email
    and sends; the speaker activates and can then join the meeting room."""
    from events.permissions import can_edit_event
    from video.services import can_enter_event

    e = _special_event("masochism-e2e")
    # Co-speaker who is an LSP member (already has a login; no invite needed).
    member = User.objects.create_user(
        email="swales@x.test", first_name="Stephanie", last_name="Swales",
    )
    e.member_speakers.add(member)
    # External speaker, comma in name, no email — the Derek case.
    derek = Speaker.objects.create(name="Derek Hook, Ph.D.", slug="derek-e2e")
    e.speakers.add(derek)

    pc = _pc_user()
    client.force_login(pc)

    # 1. Edit page surfaces Derek with the add-email affordance.
    resp = client.get(reverse("events:edit", args=[e.slug]))
    assert b"Derek Hook, Ph.D." in resp.content
    assert b"No email on file" in resp.content

    # 2. PC adds the email and sends in one step.
    client.post(
        reverse("events:speaker_invite", args=[e.slug, derek.pk]),
        {"email": "derek@x.test", "message": "Please join us."},
    )
    derek.refresh_from_db()
    assert derek.email == "derek@x.test"
    assert derek.user is not None
    assert derek.user.profile.role == Profile.Role.EXTERNAL
    assert len(mail.outbox) == 1
    inv = SpeakerInvitation.objects.get(speaker=derek)

    # 3. Derek activates via the link (fresh, logged-out client).
    activate_client = client.__class__()
    url = reverse("events:speaker_invitation_accept", args=[inv.token])
    resp = activate_client.post(
        url, {"new_password1": "Sw0rdfish!42", "new_password2": "Sw0rdfish!42"}
    )
    assert resp.status_code == 302
    assert resp.url == reverse("events:detail", args=[e.slug])

    # 4. Derek is now a presenter with room access; the co-member is unaffected.
    derek.user.refresh_from_db()
    assert can_edit_event(derek.user, e) is True
    assert can_enter_event(e, derek.user) is True
    assert e.is_presenter(member) is True   # member-speaker still works
