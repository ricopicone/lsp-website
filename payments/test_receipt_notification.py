"""The receipt bell row must link somewhere the member can actually reach.

``payments:thanks`` deliberately 404s registration payments (it's a public page
and mustn't leak registration payments), so a registration receipt has to point
at the registration confirmation page — the same landing Stripe uses for
registration checkouts.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier
from notifications.models import Notification
from payments import notifications as notify_payments
from payments.models import Payment, Receipt
from registrations.models import Registration


@pytest.fixture
def user(db):
    return User.objects.create_user(email="r@example.com", password="testpass-XYZ")


@pytest.fixture
def registration(db, user):
    event = Event.objects.create(
        title="Seminar", slug="seminar",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("560.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("560.00"), status=Registration.Status.PAID,
    )


def _paid(payment_type, user, **kwargs):
    payment = Payment.objects.create(
        payment_type=payment_type, user=user,
        amount=Decimal("560.00"), status=Payment.Status.SUCCEEDED, **kwargs
    )
    Receipt.create_for_payment(payment)
    return payment


@pytest.mark.django_db
def test_registration_receipt_links_to_the_confirmation_page(user, registration):
    payment = _paid(Payment.Type.REGISTRATION, user, registration=registration)

    notify_payments.payment_receipt(payment)

    note = Notification.objects.get(recipient=user, category="payment_receipt")
    assert note.url == reverse("registrations:confirm", args=[registration.id])


@pytest.mark.django_db
def test_registration_receipt_link_resolves(client, user, registration):
    payment = _paid(Payment.Type.REGISTRATION, user, registration=registration)
    notify_payments.payment_receipt(payment)
    note = Notification.objects.get(recipient=user, category="payment_receipt")

    client.force_login(user)
    assert client.get(note.url).status_code == 200


def test_confirmation_path_matches_the_repair_migration():
    """notifications/0011 rewrites old rows to a hardcoded path (migrations
    shouldn't call reverse) — keep the two in step."""
    assert reverse("registrations:confirm", args=[7]) == "/registrations/7/confirmation/"


@pytest.mark.django_db
def test_dues_receipt_still_links_to_the_thanks_page(user):
    payment = _paid(Payment.Type.DUES, user)

    notify_payments.payment_receipt(payment)

    note = Notification.objects.get(recipient=user, category="payment_receipt")
    assert note.url == reverse("payments:thanks", args=[payment.id])
