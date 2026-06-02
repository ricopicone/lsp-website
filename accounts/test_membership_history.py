"""Tests for the membership timeline + provenance (Phase 1 of intake)."""

from __future__ import annotations

import pytest

from accounts.models import MemberIntakeSurvey, MembershipTenure, Profile, Source, User


def _user(email="t@x.test"):
    return User.objects.create_user(email=email, password="x")


@pytest.mark.django_db
def test_role_at_picks_the_covering_tenure():
    u = _user()
    MembershipTenure.objects.create(
        user=u, role=Profile.Role.PRE_CANDIDATE, start_ay=2018, end_ay=2020,
    )
    MembershipTenure.objects.create(
        user=u, role=Profile.Role.CANDIDATE, start_ay=2021, end_ay=None,
    )
    assert MembershipTenure.role_at(u, 2019) == Profile.Role.PRE_CANDIDATE
    assert MembershipTenure.role_at(u, 2020) == Profile.Role.PRE_CANDIDATE  # inclusive end
    assert MembershipTenure.role_at(u, 2023) == Profile.Role.CANDIDATE      # ongoing
    assert MembershipTenure.role_at(u, 2017) is None                        # before any tenure
    assert MembershipTenure.role_at(u, 2020) != Profile.Role.CANDIDATE


@pytest.mark.django_db
def test_was_in_training():
    u = _user()
    MembershipTenure.objects.create(
        user=u, role=Profile.Role.CANDIDATE, start_ay=2021, end_ay=2024,
    )
    MembershipTenure.objects.create(
        user=u, role=Profile.Role.ANALYST, start_ay=2025, end_ay=None,
    )
    assert MembershipTenure.was_in_training(u, 2022) is True
    assert MembershipTenure.was_in_training(u, 2025) is False  # analyst, not in-training
    assert MembershipTenure.was_in_training(u, 2010) is False  # no tenure


@pytest.mark.django_db
def test_intake_survey_defaults():
    u = _user()
    s = MemberIntakeSurvey.objects.create(user=u)
    assert s.grid == {}
    assert s.submitted_at is None
    assert "draft" in str(s)


@pytest.mark.django_db
def test_source_default_is_staff():
    from payments.models import Payment
    p = Payment.objects.create(
        payment_type=Payment.Type.DONATION, amount=10, email="x@x.test",
    )
    assert p.source == Source.STAFF


@pytest.mark.django_db
def test_complete_payment_tags_stripe_verified():
    from payments.models import Payment
    from payments.operations import complete_payment

    p = Payment.objects.create(
        payment_type=Payment.Type.DONATION, amount=25, email="d@x.test",
        method=Payment.Method.STRIPE, status=Payment.Status.PENDING,
    )
    complete_payment(p)
    p.refresh_from_db()
    assert p.status == Payment.Status.SUCCEEDED
    assert p.source == Source.VERIFIED


@pytest.mark.django_db
def test_complete_payment_offline_keeps_staff():
    from payments.models import Payment
    from payments.operations import complete_payment

    p = Payment.objects.create(
        payment_type=Payment.Type.DONATION, amount=25, email="o@x.test",
        method=Payment.Method.OFFLINE, status=Payment.Status.PENDING,
    )
    complete_payment(p)
    p.refresh_from_db()
    assert p.source == Source.STAFF  # offline → not auto-verified
