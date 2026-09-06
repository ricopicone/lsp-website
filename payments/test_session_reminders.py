"""The day-before reminder to confirmed registrants (task #716).

Nothing reminded an event's registrants that it was about to begin: the
"starting soon" reminders cover workgroup meetings, and event sessions are not
mirrored there. Stephanie Swales' registrant wrote the day before asking for a
link. Now each session reminds its paid and comped registrants about a day
ahead, with the same joining block the confirmation carried, riding the
five-minute meeting-reminders command the host already runs.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from events.models import Audience, Event, PriceTier, Session
from notifications.categories import Category
from notifications.models import Notification
from registrations.models import Registration


@pytest.fixture
def _daily_on():
    with override_settings(
        DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co",
        SITE_BASE_URL="https://lacanschool.org",
    ):
        yield


def _event(**kw):
    kw.setdefault("title", "Working with Masochism")
    kw.setdefault("slug", "working-with-masochism")
    kw.setdefault("event_type", Event.Type.SPECIAL_EVENT)
    kw.setdefault("start_date", timezone.localdate() + dt.timedelta(days=1))
    kw.setdefault("end_date", timezone.localdate() + dt.timedelta(days=1))
    kw.setdefault("published", True)
    kw.setdefault("status", Event.Status.OPEN)
    return Event.objects.create(**kw)


def _session(event, hours_ahead, sequence=1, **kw):
    start = timezone.now() + dt.timedelta(hours=hours_ahead)
    return Session.objects.create(
        event=event, sequence=sequence, start_at=start,
        end_at=start + dt.timedelta(hours=2), **kw,
    )


def _register(event, email, status, first_name="", tier=None):
    user = User.objects.create_user(email=email, password="x", first_name=first_name)
    tier = tier or PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("50.00"), status=status,
    )


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Run the reminder command with on-commit email actually sent (the
    notifications layer sends mail on commit, which the test DB never fires)."""
    def _go(**opts):
        out = StringIO()
        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_meeting_reminders", stdout=out, **opts)
        return out.getvalue()
    return _go


@pytest.mark.django_db
def test_session_within_a_day_reminds_confirmed_registrants_once(
    run, mailoutbox, _daily_on,
):
    event = _event()
    session = _session(event, hours_ahead=20)
    tier = PriceTier.objects.create(event=event, audience=Audience.ALL, base_amount=Decimal("50"))
    paid = _register(event, "paid@example.test", Registration.Status.PAID, "Pat", tier)
    _register(event, "comped@example.test", Registration.Status.COMPED, "Cam", tier)
    _register(event, "awaiting@example.test", Registration.Status.AWAITING_PAYMENT, "", tier)
    _register(event, "gone@example.test", Registration.Status.CANCELLED, "", tier)

    out = run()
    assert "reminded for 1 event session(s), 2 registrant-notice(s)" in out
    assert {m.to[0] for m in mailoutbox} == {"paid@example.test", "comped@example.test"}
    m = next(m for m in mailoutbox if m.to == ["paid@example.test"])
    assert m.subject == "Tomorrow: Working with Masochism"
    assert m.body.startswith("Pat,")
    assert "begins" in m.body
    assert "There is no separate meeting link" in m.body
    assert "https://lacanschool.org/events/working-with-masochism/" in m.body
    assert "notification settings" in m.body
    # Bell row, linking to the event page.
    n = Notification.objects.get(recipient=paid.user, category=Category.EVENT_REMINDER)
    assert n.title == "Tomorrow: Working with Masochism"
    assert n.url == "/events/working-with-masochism/"

    # Stamped, so the five-minute timer does not send it again.
    session.refresh_from_db()
    assert session.reminder_sent_at is not None
    mailoutbox.clear()
    run()
    assert mailoutbox == []


@pytest.mark.django_db
def test_sessions_further_out_or_already_started_are_left_alone(run, mailoutbox, _daily_on):
    event = _event()
    _register(event, "paid@example.test", Registration.Status.PAID)
    _session(event, hours_ahead=30, sequence=1)   # beyond the day-ahead window
    _session(event, hours_ahead=-1, sequence=2)   # already begun
    out = run()
    assert "reminded for 0 event session(s)" in out
    assert mailoutbox == []


@pytest.mark.django_db
def test_unpublished_event_sessions_are_not_reminded(run, mailoutbox, _daily_on):
    event = _event(published=False)
    _register(event, "paid@example.test", Registration.Status.PAID)
    _session(event, hours_ahead=5)
    run()
    assert mailoutbox == []


@pytest.mark.django_db
def test_multi_session_reminder_names_the_session_and_external_link(run, mailoutbox, _daily_on):
    event = _event(
        slug="zoomed", online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242",
        end_date=timezone.localdate() + dt.timedelta(days=60),
    )
    _register(event, "paid@example.test", Registration.Status.PAID)
    _session(event, hours_ahead=10, sequence=1, title="Freud's Project")
    _session(event, hours_ahead=24 * 8, sequence=2)
    run()
    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    assert "(session 1 of 2: Freud's Project)" in body
    assert "https://zoom.example.com/j/424242" in body
    assert "Join the meeting room" not in body


@pytest.mark.django_db
def test_dry_run_reports_without_sending_or_stamping(run, mailoutbox, _daily_on):
    event = _event()
    _register(event, "paid@example.test", Registration.Status.PAID)
    session = _session(event, hours_ahead=5)
    out = run(dry_run=True)
    assert "would remind registrants" in out
    assert mailoutbox == []
    session.refresh_from_db()
    assert session.reminder_sent_at is None


@pytest.mark.django_db
def test_member_can_turn_the_email_off_and_keep_the_bell(run, mailoutbox, _daily_on):
    from notifications.categories import EmailDelivery
    from notifications.models import NotificationPreference

    event = _event()
    reg = _register(event, "paid@example.test", Registration.Status.PAID)
    _session(event, hours_ahead=5)
    pref = NotificationPreference.objects.create(user=reg.user)
    pref.set(Category.EVENT_REMINDER, in_app=True, email=EmailDelivery.OFF)
    pref.save()
    run()
    assert mailoutbox == []
    assert Notification.objects.filter(
        recipient=reg.user, category=Category.EVENT_REMINDER
    ).exists()


# ---- The other registrant emails say how to join, too ---------------------


@pytest.mark.django_db
def test_approved_and_payment_reminder_tell_the_unpaid_how_they_will_join(
    mailoutbox, _daily_on,
):
    from payments.emails import send_payment_reminder, send_registration_approved

    event = _event()
    reg = _register(event, "new@example.test", Registration.Status.AWAITING_PAYMENT)
    send_registration_approved(reg)
    send_payment_reminder(reg)
    for m in mailoutbox:
        assert "Once your registration is complete" in m.body
        assert "Join the meeting room" in m.body
        assert "https://lacanschool.org/events/working-with-masochism/" in m.body


@pytest.mark.django_db
def test_unpaid_note_never_leaks_an_external_link(mailoutbox, _daily_on):
    from payments.emails import send_registration_approved

    event = _event(
        slug="zoomed", online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242",
    )
    reg = _register(event, "new@example.test", Registration.Status.AWAITING_PAYMENT)
    send_registration_approved(reg)
    body = mailoutbox[0].body
    assert "zoom.example.com" not in body
    assert "once your registration is complete" in body


@pytest.mark.django_db
def test_installment_reminder_carries_the_joining_block(mailoutbox, _daily_on):
    from payments.emails import send_installment_reminder
    from payments.models import RegistrationInstallment

    event = _event()
    reg = _register(event, "plan@example.test", Registration.Status.PAID)
    inst = RegistrationInstallment.objects.create(
        registration=reg, sequence=1, amount=Decimal("25.00"),
        due_date=timezone.localdate(),
    )
    send_installment_reminder(inst)
    body = mailoutbox[0].body
    assert "How to join" in body
    assert "Join the meeting room" in body


@pytest.mark.django_db
def test_confirmation_page_shows_where_it_meets_once_paid(client, _daily_on):
    from django.urls import reverse

    event = _event()
    reg = _register(event, "paid@example.test", Registration.Status.PAID)
    client.force_login(reg.user)
    body = client.get(reverse("registrations:confirm", args=[reg.id])).content.decode()
    assert "Where it meets" in body
    assert "Online · video meeting" in body
    assert "Test your video" in body


@pytest.mark.django_db
def test_confirmation_page_hides_the_venue_until_paid(client, _daily_on):
    from django.urls import reverse

    event = _event(access_info="Secret room 4")
    reg = _register(event, "new@example.test", Registration.Status.AWAITING_PAYMENT)
    client.force_login(reg.user)
    body = client.get(reverse("registrations:confirm", args=[reg.id])).content.decode()
    assert "Where it meets" not in body
    assert "Secret room 4" not in body
