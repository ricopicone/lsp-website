from datetime import date
from decimal import Decimal

import pytest

from accounts.lifecycle import clear_deceased, set_deceased, sync_referral_listing  # noqa: F401
from accounts.models import Profile, User
from payments.models import Charge
from referrals.models import ReferralListMember


@pytest.mark.django_db
def test_set_deceased_disables_login_and_waives_and_delists_referrals():
    u = User.objects.create_user(email="dec@example.com")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("150"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )
    rlm = ReferralListMember.objects.create(user=u, is_active=True)

    set_deceased(u, date(2026, 7, 22))

    u.refresh_from_db()
    assert u.is_active is False
    assert u.profile.deceased_on == date(2026, 7, 22)
    assert not Charge.objects.filter(user=u, status=Charge.Status.OPEN).exists()
    rlm.refresh_from_db()
    assert rlm.is_active is False


@pytest.mark.django_db
def test_removed_standing_delists_referrals_but_does_not_waive():
    from accounts.membership import record_membership_change
    u = User.objects.create_user(email="rmv@example.com")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    Charge.objects.create(
        user=u, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2025, 9, 1), status=Charge.Status.OPEN,
    )
    rlm = ReferralListMember.objects.create(user=u, is_active=True)

    record_membership_change(
        u, role=Profile.Role.CANDIDATE, standing=Profile.Standing.REMOVED,
        effective_ay=2026,
    )

    rlm.refresh_from_db()
    assert rlm.is_active is False                       # delisted
    assert Charge.objects.filter(                       # NOT auto-waived
        user=u, status=Charge.Status.OPEN).exists()


@pytest.mark.django_db
def test_clear_deceased_reenables_login():
    u = User.objects.create_user(email="rev@example.com")
    set_deceased(u, date(2026, 7, 22))
    clear_deceased(u)
    u.refresh_from_db()
    assert u.is_active is True
    assert u.profile.deceased_on is None
