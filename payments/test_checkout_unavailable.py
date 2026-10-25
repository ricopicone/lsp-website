"""A Stripe failure at Checkout is a message, not a server error (task #820)."""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

import pytest
import stripe
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from payments.models import Payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def test_a_stripe_error_at_register_returns_with_a_message(client):
    from datetime import date

    event = Event.objects.create(
        title="Talk", slug="talk", event_type=Event.Type.SPECIAL_EVENT,
        published=True, status=Event.Status.OPEN,
        start_date=date(2027, 1, 1), end_date=date(2027, 1, 1),
    )
    tier = PriceTier.objects.create(event=event, audience=Audience.ALL,
                                    base_amount=Decimal("40.00"))
    user = User.objects.create_user(email="m@example.com", password="x")
    user.profile.role = Profile.Role.ANALYST
    user.profile.save()
    client.force_login(user)
    url = reverse("registrations:register", args=[event.slug])

    with mock.patch("stripe.checkout.Session.create",
                    side_effect=stripe.error.APIConnectionError("down")):
        response = client.post(url, {"price_tier": tier.pk}, HTTP_REFERER="http://testserver" + url,
                               follow=True)

    assert response.status_code == 200
    assert "couldn&#x27;t reach the payment service" in response.content.decode()
    assert not Payment.objects.exists()  # no PENDING row for a session that never opened
    # The place is held, so trying again is one Pay button away.
    assert Registration.objects.get().status == Registration.Status.AWAITING_PAYMENT
