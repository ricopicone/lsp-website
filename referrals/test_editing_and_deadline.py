"""Editing a request before it goes out, and the receipt-anchored response
deadline (tasks #684 and #706).

The coordinator's ask: a request arrived with the person's name in the
description and there was no way to remove it before distribution; and the
ten-day response window should count from the day the referral was received,
not from the day she pressed Distribute, so her processing delay does not
cost the analysand time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import StaffRole
from referrals import services
from referrals.models import ReferralListMember, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db

PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def coordinator(client):
    user = User.objects.create_user(
        email="diana@example.com", password="pw",
        first_name="Diana", last_name="Cuello",
    )
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.REFERRAL_COORDINATOR,
        defaults={"name": "Referral Coordinator"},
    )
    role.holders.add(user)
    client.force_login(user)
    return user


@pytest.fixture
def listed():
    user = User.objects.create_user(
        email="analyst@example.com", password="pw",
        first_name="Anna", last_name="Analyst",
    )
    return ReferralListMember.objects.create(
        user=user, onboarded_at=timezone.now(),
    )


def make_request(**overrides) -> ReferralRequest:
    defaults = dict(
        name="Alex Patient",
        pronouns="they/them",
        email="inquirer@example.com",
        location="Brooklyn, NY",
        language="English",
        modalities="By online video",
        additional_information=(
            "My name is Alex Patient and I am looking for a Lacanian analyst."
        ),
    )
    defaults.update(overrides)
    return ReferralRequest.objects.create(**defaults)


def _received_on(req: ReferralRequest, local_dt: datetime) -> ReferralRequest:
    """Pin ``created_at`` (auto_now_add ignores the create() kwarg)."""
    ReferralRequest.objects.filter(pk=req.pk).update(
        created_at=local_dt.replace(tzinfo=PACIFIC),
    )
    req.refresh_from_db()
    return req


# ---- Editing the request (task #684) ----------------------------------------


def test_edit_page_shows_the_fields(client, coordinator):
    req = make_request()
    resp = client.get(reverse("referrals:edit", args=[req.reference]))
    assert resp.status_code == 200
    assert b"My name is Alex Patient" in resp.content


def test_edit_saves_scrubbed_details_and_leaves_an_audit_line(
    client, coordinator,
):
    req = make_request()
    resp = client.post(reverse("referrals:edit", args=[req.reference]), {
        "name": "Alex Patient",
        "pronouns": "they/them",
        "email": "inquirer@example.com",
        "location": "Brooklyn, NY",
        "language": "English",
        "modalities": "By online video",
        "additional_information": "I am looking for a Lacanian analyst.",
    })
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.additional_information == "I am looking for a Lacanian analyst."
    assert "Edited the request" in req.coordinator_notes
    assert "details" in req.coordinator_notes
    assert coordinator.email in req.coordinator_notes


def test_edit_without_changes_writes_no_audit_line(client, coordinator):
    req = make_request()
    client.post(reverse("referrals:edit", args=[req.reference]), {
        "name": req.name,
        "pronouns": req.pronouns,
        "email": req.email,
        "location": req.location,
        "language": req.language,
        "modalities": req.modalities,
        "additional_information": req.additional_information,
    })
    req.refresh_from_db()
    assert req.coordinator_notes == ""


def test_scrubbed_details_are_what_clinicians_receive(
    client, coordinator, listed, django_capture_on_commit_callbacks,
):
    """The respond page and the distribution email both read the record, so
    the scrub has to land on the record — a copy edited only in the outgoing
    email would leave the name on the site."""
    req = make_request()
    client.post(reverse("referrals:edit", args=[req.reference]), {
        "name": req.name, "pronouns": req.pronouns, "email": req.email,
        "location": req.location, "language": req.language,
        "modalities": req.modalities,
        "additional_information": "Looking for a Lacanian analyst.",
    })
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("referrals:distribute", args=[req.reference]))
    msg = next(m for m in mail.outbox if m.to == ["analyst@example.com"])
    assert "My name is" not in msg.body
    assert "Looking for a Lacanian analyst." in msg.body

    client.force_login(listed.user)
    page = client.get(reverse("referrals:respond", args=[req.reference]))
    assert b"My name is" not in page.content


def test_edit_available_on_a_held_request(client, coordinator):
    """Release distributes at once when distribution is automatic, so the
    scrub has to be possible *before* release."""
    req = make_request(status=ReferralRequest.Status.HELD, held_reason="x")
    resp = client.get(reverse("referrals:edit", args=[req.reference]))
    assert resp.status_code == 200


def test_edit_refused_on_a_redacted_request(client, coordinator):
    req = make_request(purged_at=timezone.now())
    resp = client.get(reverse("referrals:edit", args=[req.reference]))
    assert resp.status_code == 302


def test_edit_forbidden_without_role(client):
    req = make_request()
    user = User.objects.create_user(email="nobody@example.com", password="pw")
    client.force_login(user)
    assert client.get(
        reverse("referrals:edit", args=[req.reference]),
    ).status_code == 403


def test_detail_page_links_to_edit(client, coordinator):
    req = make_request()
    resp = client.get(reverse("referrals:detail", args=[req.reference]))
    assert reverse("referrals:edit", args=[req.reference]).encode() in resp.content


# ---- The distribute preview -------------------------------------------------


def test_distribute_get_previews_the_outgoing_email(client, coordinator, listed):
    req = make_request()
    resp = client.get(reverse("referrals:distribute", args=[req.reference]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "My name is Alex Patient" in body        # what will go out
    assert "inquirer@example.com" not in body        # withheld
    assert reverse("referrals:edit", args=[req.reference]) in body
    assert not mail.outbox                           # GET sends nothing
    req.refresh_from_db()
    assert req.distributed_at is None


def test_distribute_post_uses_the_chosen_deadline(
    client, coordinator, listed, django_capture_on_commit_callbacks,
):
    req = make_request()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("referrals:distribute", args=[req.reference]),
            {"responses_due_at": "2026-12-24"},
        )
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    due = timezone.localtime(req.responses_due_at)
    assert (due.year, due.month, due.day) == (2026, 12, 24)
    assert (due.hour, due.minute) == (23, 59)   # end of the named day
    msg = next(m for m in mail.outbox if m.to == ["analyst@example.com"])
    assert "December 24, 2026" in msg.body


def test_distribute_post_without_a_deadline_uses_the_default(
    client, coordinator, listed,
):
    """Existing callers post the bare button; the default still applies."""
    req = make_request()
    client.post(reverse("referrals:distribute", args=[req.reference]))
    req.refresh_from_db()
    assert req.responses_due_at is not None


def test_distribute_post_with_a_bad_deadline_sends_nothing(
    client, coordinator, listed,
):
    req = make_request()
    resp = client.post(
        reverse("referrals:distribute", args=[req.reference]),
        {"responses_due_at": "not-a-date"},
    )
    assert resp.status_code == 200
    req.refresh_from_db()
    assert req.distributed_at is None
    assert not mail.outbox


# ---- The deadline counts from receipt (task #706) ---------------------------


def test_default_deadline_counts_from_the_day_received():
    """Her worked example: received Aug 24, ten-day window, due Sept 3 at the
    end of the day (school time), however late Distribute is pressed."""
    req = _received_on(make_request(), datetime(2026, 8, 24, 9, 0))
    now = datetime(2026, 8, 27, 10, 0, tzinfo=PACIFIC)
    due = timezone.localtime(services.default_response_deadline(req, now=now))
    assert (due.year, due.month, due.day) == (2026, 9, 3)
    assert (due.hour, due.minute, due.second) == (23, 59, 59)


def test_default_deadline_uses_the_school_local_receipt_date():
    """An evening submission is already tomorrow in UTC; the receipt date is
    the school's (local-date-not-utc-date)."""
    req = _received_on(make_request(), datetime(2026, 8, 24, 21, 30))
    assert req.created_at.date() == datetime(2026, 8, 25).date()  # UTC
    now = datetime(2026, 8, 25, 10, 0, tzinfo=PACIFIC)
    due = timezone.localtime(services.default_response_deadline(req, now=now))
    assert (due.month, due.day) == (9, 3)


def test_default_deadline_never_lands_in_the_past():
    """Distributed well after the window has elapsed: clinicians still get a
    few days, rather than a deadline already gone."""
    req = _received_on(make_request(), datetime(2026, 8, 1, 9, 0))
    now = datetime(2026, 8, 27, 10, 0, tzinfo=PACIFIC)
    due = timezone.localtime(services.default_response_deadline(req, now=now))
    floor = (now + timedelta(days=services.MIN_RESPONSE_DAYS)).date()
    assert due.date() == floor


def test_distribute_writes_the_receipt_anchored_deadline(listed):
    config = ReferralSettings.load()
    config.response_window_days = 10
    config.save()
    req = _received_on(
        make_request(), timezone.localtime() - timedelta(days=4),
    )
    services.distribute(req)
    req.refresh_from_db()
    expected = timezone.localdate(req.created_at) + timedelta(days=10)
    assert timezone.localdate(req.responses_due_at) == expected
