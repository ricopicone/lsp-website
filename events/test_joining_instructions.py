"""Telling registrants how to join (task #716).

The day before her special event, Stephanie Swales got a worried email from a
registrant who thought she needed to send a meeting link. Nothing had told
registrants that the Join button on the event page *is* the link. Faculty and
staff can now email everyone with a confirmed registration a reminder, in
their own words, with the joining details added by the site from one
description of where the event meets — the same block the confirmation email
carries.
"""

from __future__ import annotations

import datetime as dt
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from committees.models import Committee
from events.joining import joining_details, joining_recipients, recipient_addresses
from events.models import Audience, Event, JoiningInstructionsSend, PriceTier, Session
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
    kw.setdefault("start_date", dt.date(2026, 9, 6))
    kw.setdefault("end_date", dt.date(2026, 9, 6))
    kw.setdefault("published", True)
    kw.setdefault("status", Event.Status.OPEN)
    return Event.objects.create(**kw)


def _tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50.00")
    )


def _register(event, email, status, first_name="", tier=None):
    user = User.objects.create_user(email=email, password="x", first_name=first_name)
    return Registration.objects.create(
        user=user, event=event, price_tier=tier or _tier(event),
        quoted_amount=Decimal("50.00"), status=status,
    )


@pytest.fixture
def event(db):
    return _event()


@pytest.fixture
def roster(event):
    """Two confirmed registrants, three who must not be emailed."""
    tier = _tier(event)
    paid = _register(event, "paid@example.test", Registration.Status.PAID, "Pat", tier)
    comped = _register(event, "comped@example.test", Registration.Status.COMPED, "Cam", tier)
    _register(event, "awaiting@example.test", Registration.Status.AWAITING_PAYMENT, "", tier)
    _register(event, "pending@example.test", Registration.Status.PENDING_APPROVAL, "", tier)
    _register(event, "gone@example.test", Registration.Status.CANCELLED, "", tier)
    return paid, comped


@pytest.fixture
def presenter(event):
    """A member speaker of the special event — its faculty surface (task #463)."""
    u = User.objects.create_user(
        email="stephanie@example.test", password="x",
        first_name="Stephanie", last_name="Swales",
    )
    event.member_speakers.add(u)
    return u


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc@example.test", password="x", first_name="Pia")
    Committee.objects.get(slug="programming-committee").add_member(
        u, start_date=dt.date(2026, 1, 1)
    )
    return u


def _url(event):
    return reverse("events:joining_instructions", args=[event.slug])


# ---- One description of where the event meets ----------------------------


@pytest.mark.django_db
def test_insite_event_describes_the_join_button(event, _daily_on):
    j = joining_details(event)
    assert j.kind == "insite"
    assert j.event_url == "https://lacanschool.org/events/working-with-masochism/"
    assert j.system_check_url.endswith("/video/system-check/")


@pytest.mark.django_db
def test_external_event_carries_its_link(db, _daily_on):
    e = _event(
        slug="zoomed", online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242",
    )
    j = joining_details(e)
    assert j.kind == "external"
    assert j.access_info == "https://zoom.example.com/j/424242"


@pytest.mark.django_db
def test_in_person_event_is_never_a_video_room(db, _daily_on):
    e = _event(slug="room", format=Event.Format.IN_PERSON, access_info="220 Montgomery St")
    assert joining_details(e).kind == "in_person"


@pytest.mark.django_db
def test_online_event_with_video_off_promises_nothing(event):
    """Video switched off site-wide: don't describe a room that isn't there."""
    with override_settings(DAILY_ENABLED=False):
        assert joining_details(event).kind == "online_unknown"


@pytest.mark.django_db
def test_next_session_start_is_the_time_named(event, _daily_on):
    Session.objects.create(
        event=event, sequence=1,
        start_at=dt.datetime(2099, 9, 6, 17, 0, tzinfo=dt_timezone.utc),
        end_at=dt.datetime(2099, 9, 6, 19, 0, tzinfo=dt_timezone.utc),
    )
    assert joining_details(event).next_start_at.year == 2099


# ---- Who receives it -----------------------------------------------------


@pytest.mark.django_db
def test_recipients_are_the_confirmed_registrants_only(event, roster):
    emails = {r.user.email for r in joining_recipients(event)}
    assert emails == {"paid@example.test", "comped@example.test"}
    assert recipient_addresses(event) == ["comped@example.test", "paid@example.test"]


# ---- The page ------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_is_sent_to_login(client, event):
    r = client.get(_url(event))
    assert r.status_code == 302 and "/accounts/login/" in r["Location"]


@pytest.mark.django_db
def test_a_registrant_cannot_reach_it(client, event, roster):
    client.force_login(roster[0].user)
    assert client.get(_url(event)).status_code == 404


@pytest.mark.django_db
def test_presenter_sees_recipients_addresses_and_signs_as_herself(
    client, event, roster, presenter, _daily_on,
):
    client.force_login(presenter)
    body = client.get(_url(event)).content.decode()
    assert "Recipients" in body and "(2)" in body
    assert "paid@example.test, comped@example.test" in body or \
        "comped@example.test, paid@example.test" in body
    assert 'value="me" class="radio radio-sm mt-0.5" checked' in body
    # The preview already carries the fixed joining block.
    assert "Join the meeting room" in body
    assert "https://lacanschool.org/events/working-with-masochism/" in body


@pytest.mark.django_db
def test_registrar_operator_sees_it_and_signs_as_the_school(
    client, event, roster, pc_member, _daily_on,
):
    client.force_login(pc_member)
    body = client.get(_url(event)).content.decode()
    assert 'value="school" class="radio radio-sm mt-0.5" checked' in body


@pytest.mark.django_db
def test_external_event_with_no_link_warns_before_sending(client, pc_member, _daily_on):
    e = _event(slug="zoomed", online_venue=Event.OnlineVenue.EXTERNAL)
    client.force_login(pc_member)
    body = client.get(_url(e)).content.decode()
    assert "currently empty" in body


# ---- Sending -------------------------------------------------------------


@pytest.mark.django_db
def test_send_emails_each_confirmed_registrant_in_the_senders_voice(
    client, event, roster, presenter, mailoutbox, _daily_on,
):
    client.force_login(presenter)
    r = client.post(_url(event), {
        "message": "See you tomorrow at 10. Bring the Freud.",
        "sign_as": "me",
    })
    assert r.status_code == 302
    assert len(mailoutbox) == 2
    to = {m.to[0] for m in mailoutbox}
    assert to == {"paid@example.test", "comped@example.test"}
    m = next(m for m in mailoutbox if m.to == ["paid@example.test"])
    assert m.subject == "How to join: Working with Masochism"
    assert m.body.startswith("Pat,")
    assert "See you tomorrow at 10. Bring the Freud." in m.body
    assert "There is no separate meeting link" in m.body
    assert 'click "Join the meeting room"' in m.body
    assert "https://lacanschool.org/events/working-with-masochism/" in m.body
    assert "no app to install" in m.body
    assert "— Stephanie Swales" in m.body
    assert m.reply_to == ["stephanie@example.test"]

    send = JoiningInstructionsSend.objects.get()
    assert send.event == event and send.sent_by == presenter
    assert send.recipient_count == 2 and send.sign_as == "me"
    # The page now reports the send.
    body = client.get(_url(event)).content.decode()
    assert "Last sent" in body and "Stephanie Swales" in body


@pytest.mark.django_db
def test_signing_as_the_school_routes_replies_to_the_support_mailbox(
    client, event, roster, pc_member, mailoutbox, _daily_on, settings,
):
    settings.SUPPORT_EMAIL = "website@lacanschool.org"
    client.force_login(pc_member)
    client.post(_url(event), {"message": "A reminder.", "sign_as": "school"})
    m = mailoutbox[0]
    assert m.reply_to == ["website@lacanschool.org"]
    assert "— Lacanian School of Psychoanalysis" in m.body
    assert "Pia" not in m.body


@pytest.mark.django_db
def test_external_event_email_carries_the_link_not_the_room(
    client, pc_member, mailoutbox, _daily_on,
):
    e = _event(
        slug="zoomed", online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242\nPasscode 1234",
    )
    _register(e, "z@example.test", Registration.Status.PAID)
    client.force_login(pc_member)
    client.post(_url(e), {"message": "Hi", "sign_as": "school"})
    body = mailoutbox[0].body
    assert "https://zoom.example.com/j/424242" in body
    assert "Passcode 1234" in body
    assert "Join the meeting room" not in body


@pytest.mark.django_db
def test_nobody_confirmed_means_nothing_sent(client, event, pc_member, mailoutbox):
    _register(event, "w@example.test", Registration.Status.AWAITING_PAYMENT)
    client.force_login(pc_member)
    r = client.post(_url(event), {"message": "Hi", "sign_as": "school"}, follow=True)
    assert mailoutbox == []
    assert "nobody to email" in r.content.decode()
    assert not JoiningInstructionsSend.objects.exists()


# ---- Where the button lives ----------------------------------------------


@pytest.mark.django_db
def test_faculty_view_offers_the_button_and_the_address_copy(
    client, event, roster, presenter, _daily_on,
):
    client.force_login(presenter)
    body = client.get(
        reverse("events:detail", args=[event.slug]) + "?view=faculty"
    ).content.decode()
    assert _url(event) in body
    assert "Email joining instructions" in body
    assert "data-copy-roster-emails" in body
    assert "paid@example.test, comped@example.test" in body


@pytest.mark.django_db
def test_in_person_faculty_view_has_no_joining_button(client, pc_member):
    e = _event(slug="room", format=Event.Format.IN_PERSON)
    client.force_login(pc_member)
    body = client.get(reverse("events:detail", args=[e.slug]) + "?view=faculty").content.decode()
    assert "Email joining instructions" not in body


@pytest.mark.django_db
def test_registrar_events_tab_links_to_it(client, event, pc_member):
    client.force_login(pc_member)
    body = client.get(reverse("registrations:registrar_events")).content.decode()
    assert _url(event) in body


# ---- The confirmation email says the same thing --------------------------


@pytest.mark.django_db
def test_confirmation_email_tells_the_registrant_about_the_join_button(
    event, mailoutbox, _daily_on,
):
    from payments.emails import send_registration_confirmation

    reg = _register(event, "new@example.test", Registration.Status.PAID, "Nia")
    send_registration_confirmation(reg)
    body = mailoutbox[-1].body
    assert "How to join" in body
    assert "There is no separate meeting link" in body
    assert "https://lacanschool.org/events/working-with-masochism/" in body
    assert "Join the meeting room" in body


@pytest.mark.django_db
def test_confirmation_email_withholds_joining_until_paid(event, mailoutbox, _daily_on):
    from payments.emails import send_registration_confirmation

    reg = _register(event, "new@example.test", Registration.Status.AWAITING_PAYMENT)
    send_registration_confirmation(reg)
    body = mailoutbox[-1].body
    assert "How to join" not in body
    assert "Join the meeting room" not in body
