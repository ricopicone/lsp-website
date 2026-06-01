"""Faculty-approval registration flow (approve-first, then pay)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _approval_event(amount="50.00"):
    e = Event.objects.create(
        title="Approval Seminar", slug="appr", event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=Event.Status.OPEN, requires_faculty_approval=True,
    )
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal(amount))
    e.ensure_workgroup()
    return e


def _faculty(event, email="fac@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="Fa", last_name="Culty")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


def _student(email="stu@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="Stu", last_name="Dent")
    u.profile.role = Profile.Role.MEMBER
    u.profile.save()
    return u


def test_register_requires_approval_creates_pending_and_notifies_faculty(client):
    event = _approval_event()
    fac = _faculty(event)
    student = _student()
    client.force_login(student)

    tier = event.price_tiers.first()
    mail.outbox.clear()
    resp = client.post(reverse("registrations:register", args=[event.slug]),
                       {"price_tier": tier.pk})

    reg = Registration.objects.get(user=student, event=event)
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert resp.status_code == 302 and "confirmation" in resp.url   # not Stripe
    # Faculty got the approval-needed email.
    assert any(fac.email in m.to for m in mail.outbox)


def test_approve_nonzero_moves_to_awaiting_payment_and_emails_student(client):
    event = _approval_event("50.00")
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    mail.outbox.clear()
    client.post(reverse("registrations:approve", args=[reg.id]))

    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.approved_by == fac and reg.decided_at is not None
    assert reg.needs_payment
    assert any(student.email in m.to for m in mail.outbox)   # "approved — pay" email


def test_approve_zero_amount_moves_to_paid(client):
    event = _approval_event("0.00")
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("0.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    client.post(reverse("registrations:approve", args=[reg.id]))

    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID


def test_decline_sets_declined_and_emails_student(client):
    event = _approval_event()
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    mail.outbox.clear()
    client.post(reverse("registrations:decline", args=[reg.id]), {"reason": "Full this year"})

    reg.refresh_from_db()
    assert reg.status == Registration.Status.DECLINED
    assert reg.decline_reason == "Full this year"
    assert any(student.email in m.to for m in mail.outbox)


def test_non_faculty_cannot_approve(client):
    event = _approval_event()
    _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(_student("outsider@x.test"))
    resp = client.post(reverse("registrations:approve", args=[reg.id]))
    assert resp.status_code == 403
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL


def test_reminders_command_notifies_and_throttles(client):
    from django.core.management import call_command
    from django.utils import timezone

    event = _approval_event("50.00")
    fac = _faculty(event)
    pending = Registration.objects.create(
        user=_student("p@x.test"), event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    approved = Registration.objects.create(
        user=_student("a@x.test"), event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.AWAITING_PAYMENT,
        decided_at=timezone.now(),
    )

    mail.outbox.clear()
    call_command("send_registration_reminders")
    # Faculty reminder (to fac) + student payment reminder (to approved.user).
    assert any(fac.email in m.to for m in mail.outbox)
    assert any(approved.user.email in m.to for m in mail.outbox)
    pending.refresh_from_db()
    approved.refresh_from_db()
    assert pending.reminded_at is not None and approved.reminded_at is not None

    # Running again immediately: throttled, nothing sent.
    mail.outbox.clear()
    call_command("send_registration_reminders")
    assert mail.outbox == []
