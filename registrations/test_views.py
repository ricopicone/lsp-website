"""Tests for the public registration flow."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from accounts.models import User
from events.models import Audience, Event, PriceTier, PricingCode
from registrations.models import Registration


@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    """Replace create_checkout_session with a stub that returns a fake URL.

    The Stripe flow needs the real API to talk to a real account; tests just
    care that the view triggered it and redirected to the URL it returned.
    """
    stub = MagicMock(
        return_value=(MagicMock(id=42), MagicMock(url="https://stripe.test/session/xyz")),
    )
    monkeypatch.setattr("registrations.views.create_checkout_session", stub)
    return stub


@pytest.fixture
def faculty(db):
    user = User.objects.create_user(email="fac@example.com")
    user.profile.is_faculty = True
    user.profile.save()
    return user


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Open Seminar",
        slug="open-seminar",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.OPEN,
        published=True,
    )


@pytest.fixture
def draft_event(db):
    return Event.objects.create(
        title="Draft Seminar",
        slug="draft-seminar",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        status=Event.Status.DRAFT,
        published=False,
    )


@pytest.fixture
def standard_tier(event):
    return PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00")
    )


@pytest.fixture
def sliding_tier(event):
    return PriceTier.objects.create(
        event=event,
        audience=Audience.ALL,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )


@pytest.fixture
def tuition_tier(event):
    return PriceTier.objects.create(
        event=event,
        audience=Audience.MEMBER,
        base_amount=Decimal("100.00"),
        covered_by_tuition=True,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(email="reg@example.com", password="testpass-XYZ")


@pytest.fixture
def tuition_member(db):
    u = User.objects.create_user(email="member@example.com", password="testpass-XYZ")
    u.profile.tuition_paying = True
    u.profile.save()
    return u


# --- Permissions / event-state gating -----------------------------------


def test_anonymous_redirected_to_login(client, event):
    url = reverse("registrations:register", args=[event.slug])
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
    assert f"next={url}" in response.url or "next=" in response.url


def test_draft_event_404s_even_for_logged_in(client, draft_event, user):
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[draft_event.slug]))
    assert response.status_code == 404


def test_closed_event_404s(client, event, user):
    event.status = Event.Status.CLOSED
    event.save()
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 404


def test_unpublished_event_404s(client, event, user):
    event.published = False
    event.save()
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 404


# --- GET ----------------------------------------------------------------


def test_get_renders_form(client, event, standard_tier, user):
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 200
    assert b"Choose your tier" in response.content
    # The tier appears in the form
    assert b"Student" in response.content


# --- Happy-path POST ----------------------------------------------------


def test_post_standard_tier_redirects_to_stripe(
    client, event, standard_tier, user, stub_stripe,
):
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": standard_tier.id},
    )
    assert response.status_code == 302
    reg = Registration.objects.get(user=user, event=event)
    assert reg.quoted_amount == Decimal("100.00")
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.pricing_code is None
    assert response.url == "https://stripe.test/session/xyz"
    stub_stripe.assert_called_once()
    assert stub_stripe.call_args.args[0] == reg


def test_post_sliding_tier_with_amount_redirects_to_stripe(
    client, event, sliding_tier, user, stub_stripe,
):
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": sliding_tier.id, "sliding_amount": "35.00"},
    )
    assert response.status_code == 302
    reg = Registration.objects.get(user=user, event=event)
    assert reg.quoted_amount == Decimal("35.00")
    assert response.url == "https://stripe.test/session/xyz"
    stub_stripe.assert_called_once()


def test_post_sliding_tier_without_amount_shows_error(client, event, sliding_tier, user):
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": sliding_tier.id},
    )
    # Form re-rendered with errors; no Registration created.
    assert response.status_code == 200
    assert b"sliding_amount" in response.content or b"sliding" in response.content.lower()
    assert Registration.objects.filter(user=user, event=event).count() == 0


def test_post_sliding_zero_creates_registration_with_status_paid(
    client, event, sliding_tier, user, stub_stripe,
):
    """'None turned away' — zero sliding amount on a min=0 tier should succeed and
    immediately mark Paid, *skipping* the Stripe roundtrip."""
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": sliding_tier.id, "sliding_amount": "0"},
    )
    assert response.status_code == 302
    reg = Registration.objects.get(user=user, event=event)
    assert reg.quoted_amount == Decimal("0.00")
    assert reg.status == Registration.Status.PAID
    assert response.url == reverse("registrations:confirm", args=[reg.id])
    stub_stripe.assert_not_called()


def test_post_tuition_member_covered_by_tuition_short_circuits(
    client, event, tuition_tier, tuition_member, stub_stripe,
):
    client.force_login(tuition_member)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": tuition_tier.id},
    )
    assert response.status_code == 302
    reg = Registration.objects.get(user=tuition_member, event=event)
    assert reg.quoted_amount == Decimal("0.00")
    assert reg.status == Registration.Status.PAID
    stub_stripe.assert_not_called()


# --- Pricing codes ------------------------------------------------------


def test_post_with_valid_pricing_code_applies_discount(
    client, event, standard_tier, user, faculty, stub_stripe,
):
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
        max_uses=2,
    )
    client.force_login(user)
    client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": standard_tier.id, "pricing_code": code.code},
    )
    reg = Registration.objects.get(user=user, event=event)
    assert reg.quoted_amount == Decimal("75.00")
    assert reg.pricing_code_id == code.id
    code.refresh_from_db()
    assert code.uses_remaining == 1
    # The discounted amount is what gets sent to Stripe.
    stub_stripe.assert_called_once_with(reg)


def test_post_with_unknown_code_shows_error(client, event, standard_tier, user):
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": standard_tier.id, "pricing_code": "NOTHERE99"},
    )
    assert response.status_code == 200
    assert b"not recognized" in response.content.lower()
    assert Registration.objects.filter(user=user, event=event).count() == 0


def test_post_with_code_lowercase_normalized(
    client, event, standard_tier, user, faculty, stub_stripe,
):
    """Codes are case-insensitive on input; we uppercase before lookup."""
    code = PricingCode.objects.create(
        event=event,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("40.00"),
    )
    client.force_login(user)
    client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": standard_tier.id, "pricing_code": code.code.lower()},
    )
    reg = Registration.objects.get(user=user, event=event)
    assert reg.quoted_amount == Decimal("40.00")
    stub_stripe.assert_called_once()


# --- Confirmation page ---------------------------------------------------


def test_confirmation_page_renders_for_owner(client, event, standard_tier, user):
    client.force_login(user)
    reg = Registration.objects.create(
        user=user, event=event, price_tier=standard_tier,
        quoted_amount=Decimal("100.00"),
    )
    response = client.get(reverse("registrations:confirm", args=[reg.id]))
    assert response.status_code == 200
    assert b"Open Seminar" in response.content


def test_confirmation_page_404s_for_other_user(client, event, standard_tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=standard_tier,
        quoted_amount=Decimal("100.00"),
    )
    other = User.objects.create_user(email="other@example.com", password="testpass-XYZ")
    client.force_login(other)
    response = client.get(reverse("registrations:confirm", args=[reg.id]))
    assert response.status_code == 404


# --- Auth flow ----------------------------------------------------------


@pytest.mark.django_db
def test_login_page_renders(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert b"Log in" in response.content


@pytest.mark.django_db
def test_signup_creates_user_and_logs_in(client):
    response = client.post(
        reverse("signup"),
        {
            "email": "newperson@example.com",
            "password1": "very-strong-pass-xyz",
            "password2": "very-strong-pass-xyz",
            "first_name": "New",
            "last_name": "Person",
        },
    )
    assert response.status_code == 302
    u = User.objects.get(email="newperson@example.com")
    assert u.first_name == "New"
    assert hasattr(u, "profile")  # auto-created via signal


@pytest.mark.django_db
def test_signup_safe_next_redirect_only_relative(client):
    """The ?next= param must be a relative path; absolute URLs are rejected."""
    response = client.post(
        reverse("signup") + "?next=https://evil.example.com",
        {
            "email": "safenext@example.com",
            "password1": "very-strong-pass-xyz",
            "password2": "very-strong-pass-xyz",
        },
    )
    assert response.status_code == 302
    assert not response.url.startswith("https://evil.example.com")
