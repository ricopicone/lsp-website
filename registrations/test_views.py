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
    """Tuition-current user — has a current TuitionEnrollment with COMMITTED
    status, the source of truth for the covered-by-tuition path."""
    from payments.models import TuitionEnrollment, TuitionPeriod

    u = User.objects.create_user(email="member@example.com", password="testpass-XYZ")
    period = TuitionPeriod.current()
    if period is not None:
        TuitionEnrollment.objects.update_or_create(
            user=u, tuition_period=period,
            defaults={"status": TuitionEnrollment.Status.COMMITTED},
        )
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


def test_register_redirects_when_already_registered(client, event, standard_tier, user):
    """GET to /register/ when the user has an active reg → redirect to confirm?already=1."""
    existing = Registration.objects.create(
        user=user, event=event, price_tier=standard_tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 302
    assert response.url.endswith(
        reverse("registrations:confirm", args=[existing.id]) + "?already=1"
    )


def test_register_does_not_redirect_when_only_cancelled_exists(
    client, event, standard_tier, user, stub_stripe,
):
    """A cancelled prior registration must not block a fresh registration."""
    Registration.objects.create(
        user=user, event=event, price_tier=standard_tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.CANCELLED,
    )
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": standard_tier.id},
    )
    # New registration created and Stripe redirect happens — no "already" redirect.
    assert response.status_code == 302
    assert response.url == "https://stripe.test/session/xyz"
    assert Registration.objects.filter(
        user=user, event=event, status=Registration.Status.AWAITING_PAYMENT,
    ).count() == 1


def test_confirm_page_shows_already_notice(client, event, standard_tier, user):
    reg = Registration.objects.create(
        user=user, event=event, price_tier=standard_tier,
        quoted_amount=Decimal("100.00"),
    )
    client.force_login(user)
    response = client.get(
        reverse("registrations:confirm", args=[reg.id]) + "?already=1"
    )
    assert response.status_code == 200
    assert b"already registered" in response.content


def test_tuition_member_already_registered_redirects(
    client, event, tuition_tier, tuition_member,
):
    """Tuition short-circuit also honors the already-registered redirect."""
    tuition_tier.audience = tuition_member.profile.role
    tuition_tier.save()
    existing = Registration.objects.create(
        user=tuition_member, event=event, price_tier=tuition_tier,
        quoted_amount=Decimal("0.00"),
        status=Registration.Status.PAID,
    )
    client.force_login(tuition_member)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 302
    assert str(existing.id) in response.url


def test_post_sliding_below_floor_rejected_server_side(client, event, user, stub_stripe):
    """Server-side guarantee that below-floor never silently coerces."""
    tier = PriceTier.objects.create(
        event=event,
        audience=Audience.STUDENT,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("25.00"),
    )
    client.force_login(user)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"price_tier": tier.id, "sliding_amount": "10.00"},
    )
    assert response.status_code == 200
    assert b"below minimum" in response.content
    assert Registration.objects.filter(user=user, event=event).count() == 0
    stub_stripe.assert_not_called()


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


def test_tuition_member_gets_covered_short_circuit_page(
    client, event, tuition_tier, tuition_member,
):
    """GET with a covered tier renders the one-click confirm panel, not the form."""
    # Make the covered tier match the user's role so _find_covered_tier picks it.
    tuition_tier.audience = tuition_member.profile.role
    tuition_tier.save()
    client.force_login(tuition_member)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    assert response.status_code == 200
    assert b"included in your tuition" in response.content
    assert b"Confirm registration" in response.content
    # The regular tier picker should not be on this page.
    assert b"Choose your tier" not in response.content


def test_tuition_member_covered_confirm_creates_paid_registration(
    client, event, tuition_tier, tuition_member, stub_stripe,
):
    tuition_tier.audience = tuition_member.profile.role
    tuition_tier.save()
    client.force_login(tuition_member)
    response = client.post(
        reverse("registrations:register", args=[event.slug]),
        {"confirm_covered": "1"},
    )
    assert response.status_code == 302
    reg = Registration.objects.get(user=tuition_member, event=event)
    assert reg.quoted_amount == Decimal("0.00")
    assert reg.status == Registration.Status.PAID
    assert reg.price_tier == tuition_tier
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


def test_tier_label_format_in_form(client, event, standard_tier, sliding_tier, user):
    """The radio labels should be clean human text, not PriceTier.__str__."""
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    # Verbose default __str__ leaks "(event):" — make sure it doesn't appear.
    assert b"(event):" not in response.content
    # Clean labels render:
    assert b"Student" in response.content
    assert b"Sliding scale" in response.content


def test_register_form_exposes_per_tier_min_max_to_js(
    client, event, standard_tier, sliding_tier, user,
):
    """The slider needs each tier's min/max — exposed via inline JSON."""
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    body = response.content.decode()
    # Inline tiers-meta script tag carries per-tier slider config.
    assert 'id="tiers-meta"' in body
    # The sliding tier has its minimum + base exposed.
    import json as _json
    start = body.index('id="tiers-meta"')
    chunk = body[start:start + 800]
    inner = chunk.split(">", 1)[1].split("</script>")[0]
    meta = _json.loads(inner)
    assert str(sliding_tier.pk) in meta
    assert meta[str(sliding_tier.pk)]["sliding"] is True
    assert meta[str(sliding_tier.pk)]["min"] == "0.00"
    assert meta[str(sliding_tier.pk)]["max"] == "100.00"
    assert meta[str(standard_tier.pk)]["sliding"] is False


def test_pre_selects_user_role_matching_tier(
    client, event, standard_tier, sliding_tier, user,
):
    """The role-matching tier should be pre-selected (checked)."""
    user.profile.role = "student"
    user.profile.save()
    client.force_login(user)
    response = client.get(reverse("registrations:register", args=[event.slug]))
    body = response.content.decode()
    # The student tier's radio should have the checked attribute.
    needle = f'value="{standard_tier.id}"'
    pos = body.find(needle)
    assert pos != -1
    # Look at the surrounding ~200 chars for 'checked'
    assert "checked" in body[max(0, pos - 200):pos + 200]


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


# --- Tuition gating (M7.5) ---------------------------------------------


@pytest.fixture
def special_event(db):
    return Event.objects.create(
        title="Working with Masochism",
        slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 1),
        status=Event.Status.OPEN,
        published=True,
    )


@pytest.fixture
def special_event_tier(special_event):
    return PriceTier.objects.create(
        event=special_event, audience=Audience.ALL, base_amount=Decimal("50.00"),
    )


@pytest.mark.django_db
def test_undecided_in_training_student_is_blocked_from_special_event(
    client, special_event, special_event_tier,
):
    """No-decision broad gate: special-event registration is blocked."""
    from accounts.models import Profile
    u = User.objects.create_user(email="cand@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 403
    assert b"tuition decision" in resp.content


@pytest.mark.django_db
def test_undecided_in_training_student_is_blocked_from_seminar(
    client, event, standard_tier,
):
    """Broad gate: an in-training student with no tuition decision can't
    register for ANY event — seminars included. Once they pick any option
    (commit / payment plan / skip), the seminar path opens."""
    from accounts.models import Profile
    u = User.objects.create_user(email="seminar-cand@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.save()
    client.force_login(u)
    resp = client.get(reverse("registrations:register", args=[event.slug]))
    assert resp.status_code == 403
    assert b"tuition decision" in resp.content


@pytest.mark.django_db
def test_undecided_non_in_training_user_is_not_blocked(client, event, standard_tier):
    """Broad gate applies only to in-training roles — Analysts, Scholars,
    Members, and external visitors are never blocked."""
    from accounts.models import Profile
    u = User.objects.create_user(email="analyst-uds@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    client.force_login(u)
    resp = client.get(reverse("registrations:register", args=[event.slug]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_decision_unlocks_seminar_for_in_training_student(client, event, standard_tier):
    """Any decision — even SKIPPING — clears the broad gate for seminars."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod
    u = User.objects.create_user(email="seminar-skip@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    client.force_login(u)
    resp = client.get(reverse("registrations:register", args=[event.slug]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_special_event_allows_skipping_student(
    client, special_event, special_event_tier,
):
    """Skipping is an explicit choice — student pays event fee, can register."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod
    u = User.objects.create_user(email="cand2@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_special_event_blocks_committed_student_with_no_payment(
    client, special_event, special_event_tier,
):
    """COMMITTED means "I'll pay" — but until payment lands or a plan is set up,
    special-event registration is blocked. The student needs to either pay or
    switch to PAYMENT_PLAN first."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod
    u = User.objects.create_user(email="cand3@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 403
    assert b"committed to pay tuition" in resp.content


@pytest.mark.django_db
def test_special_event_allows_payment_plan_student(
    client, special_event, special_event_tier,
):
    """PAYMENT_PLAN means the plan is set up — they can register."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod
    u = User.objects.create_user(email="cand5@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.PAYMENT_PLAN,
    )
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_special_event_without_covered_tier_charges_tuition_student(
    client, special_event, special_event_tier,
):
    """Confirms the contract: a special event that has no covered_by_tuition
    tier still charges tuition-current students the standard fee. Whether an
    event is covered by tuition is decided per-event via PriceTier
    .covered_by_tuition — it's not implied by tuition status alone."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod

    # special_event_tier is the standard, non-covered tier ($50.00).
    assert special_event_tier.covered_by_tuition is False

    u = User.objects.create_user(email="cand6@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.PAID_IN_FULL,
    )
    client.force_login(u)

    # GET: the standard form should render, NOT the covered short-circuit page.
    resp = client.get(reverse("registrations:register", args=[special_event.slug]))
    assert resp.status_code == 200
    assert b"included in your tuition" not in resp.content
    # Standard form has the tier picker; covered short-circuit doesn't.
    assert b"Choose your tier" in resp.content or b"price_tier" in resp.content


@pytest.mark.django_db
def test_seminar_does_not_block_skipping_student(
    client, event, sliding_tier,
):
    """Seminars deliberately don't block — students pay regular fees if skipping."""
    from accounts.models import Profile
    from payments.models import TuitionEnrollment, TuitionPeriod
    u = User.objects.create_user(email="cand4@example.com", password="x")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    period = TuitionPeriod.current()
    TuitionEnrollment.objects.create(
        user=u, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING,
    )
    client.force_login(u)
    # event is default SEMINAR — should not block.
    resp = client.get(reverse("registrations:register", args=[event.slug]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_special_event_does_not_block_full_analyst(
    client, special_event, special_event_tier,
):
    """Non-in-training roles (Analyst, Scholar, Member) are never blocked by tuition status."""
    from accounts.models import Profile
    u = User.objects.create_user(email="analyst@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    client.force_login(u)
    resp = client.get(
        reverse("registrations:register", args=[special_event.slug])
    )
    assert resp.status_code == 200
