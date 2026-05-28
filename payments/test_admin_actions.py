"""Tests for admin manual-override actions (REG-14).

Two surfaces: PaymentAdmin's "Apply payment success" (for offline /
manual payments) and RegistrationAdmin's "Comp selected registrations".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory

from accounts.models import User
from events.models import Audience, Event, PriceTier
from payments.models import Payment, Receipt
from registrations.models import Registration


@pytest.fixture
def staff_admin(db):
    u = User.objects.create_superuser(email="admin@example.com", password="x")
    return u


@pytest.fixture
def member(db):
    return User.objects.create_user(email="m@example.com")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar", slug="seminar",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        access_info="Zoom: https://example.zoom.us/j/X",
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("100.00")
    )


def _admin_request(method, user):
    """Build a request good enough for admin actions."""
    rf = RequestFactory()
    request = rf.request()
    request.user = user
    # Django messages middleware needs a session-like storage.
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))
    return request


# ---- PaymentAdmin.apply_payment_success ------------------------------


@pytest.mark.django_db
def test_apply_payment_success_marks_paid_and_creates_receipt(
    member, event, tier, staff_admin,
):
    reg = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=member,
        amount=Decimal("100.00"),
        method=Payment.Method.OFFLINE,
        status=Payment.Status.PENDING,
        notes="Cash received at the door",
    )
    admin = site._registry[Payment]
    request = _admin_request("GET", staff_admin)
    admin.apply_payment_success(request, Payment.objects.filter(pk=payment.pk))

    payment.refresh_from_db()
    reg.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert hasattr(payment, "receipt")
    assert reg.status == Registration.Status.PAID
    # Confirmation + receipt emails.
    subjects = [m.subject for m in mail.outbox]
    assert any("Registration confirmed" in s for s in subjects)
    assert any("Receipt LSP-" in s for s in subjects)


@pytest.mark.django_db
def test_apply_payment_success_skips_already_succeeded(member, event, tier, staff_admin):
    reg = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION,
        registration=reg, user=member,
        amount=Decimal("100.00"),
        method=Payment.Method.OFFLINE,
        status=Payment.Status.SUCCEEDED,
    )
    admin = site._registry[Payment]
    request = _admin_request("GET", staff_admin)
    admin.apply_payment_success(request, Payment.objects.filter(pk=payment.pk))
    # No second receipt, no second email.
    assert Receipt.objects.filter(payment=payment).count() == 0  # never created — was skipped
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_apply_payment_success_for_dues_sends_receipt(member, staff_admin):
    payment = Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member, amount=Decimal("100.00"),
        method=Payment.Method.OFFLINE,
        status=Payment.Status.PENDING,
    )
    admin = site._registry[Payment]
    request = _admin_request("GET", staff_admin)
    admin.apply_payment_success(request, Payment.objects.filter(pk=payment.pk))
    payment.refresh_from_db()
    assert payment.status == Payment.Status.SUCCEEDED
    assert hasattr(payment, "receipt")
    assert any("Receipt LSP-" in m.subject for m in mail.outbox)


# ---- RegistrationAdmin.comp_selected_registrations -------------------


@pytest.mark.django_db
def test_comp_registration_marks_comped_and_emails(member, event, tier, staff_admin):
    reg = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    admin = site._registry[Registration]
    request = _admin_request("GET", staff_admin)
    admin.comp_selected_registrations(
        request, Registration.objects.filter(pk=reg.pk)
    )
    reg.refresh_from_db()
    assert reg.status == Registration.Status.COMPED
    assert "Comped by admin@example.com" in reg.staff_notes
    # Confirmation email sent and includes the comp explanation + access_info.
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "Registration confirmed" in msg.subject
    assert "complimentary" in msg.body.lower()
    assert "Zoom:" in msg.body  # access_info released for COMPED too


@pytest.mark.django_db
def test_comp_registration_skips_already_paid(member, event, tier, staff_admin):
    reg = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.PAID,
    )
    admin = site._registry[Registration]
    request = _admin_request("GET", staff_admin)
    admin.comp_selected_registrations(
        request, Registration.objects.filter(pk=reg.pk)
    )
    reg.refresh_from_db()
    # PAID registrations aren't touched by comp action.
    assert reg.status == Registration.Status.PAID
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_event_page_shows_access_info_to_comped_user(client, member, event, tier):
    """COMPED registrations grant access_info on the event page too (REG-8)."""
    from django.urls import reverse
    Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.COMPED,
    )
    client.force_login(member)
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Your access details" in response.content
    assert b"Zoom:" in response.content
