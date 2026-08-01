"""Which notification categories a member sees on the settings page."""

from __future__ import annotations

from datetime import date

import pytest

from accounts.models import User
from committees.models import Committee
from core.models import StaffRole
from notifications.audience import applies, visible_categories
from notifications.categories import CATEGORY_META, Category
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


def _member(email="aud-member@x.test", role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def test_ungated_categories_are_visible_to_everyone():
    user = _member()
    assert applies(user, Category.PARLETRE_MENTION)
    assert applies(user, Category.ACCOUNT_SECURITY)


def test_plan_review_is_board_only():
    plain = _member("aud-plain@x.test", role="analyst")
    assert not applies(plain, Category.TUITION_PLAN_REVIEW)

    board = _member("aud-board@x.test", role="analyst")
    Committee.objects.get(slug="board").add_member(
        board, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    assert applies(board, Category.TUITION_PLAN_REVIEW)


def test_suggestion_review_is_for_site_staff():
    plain = _member("aud-nosugg@x.test", role="analyst")
    assert not applies(plain, Category.SUGGESTION_FILED)

    staffer = _member("aud-sugg@x.test", role="analyst")
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(staffer)
    assert applies(staffer, Category.SUGGESTION_FILED)


def test_referral_requests_reach_clinicians_and_the_coordinator():
    from referrals.models import ReferralListMember

    plain = _member("aud-noref@x.test", role="analyst")
    assert not applies(plain, Category.REFERRAL_REQUEST)

    clinician = _member("aud-clinician@x.test", role="analyst")
    ReferralListMember.objects.create(user=clinician)
    assert applies(clinician, Category.REFERRAL_REQUEST)

    coordinator = _member("aud-refcoord@x.test", role="analyst")
    StaffRole.objects.get(key=StaffRole.REFERRAL_COORDINATOR).holders.add(coordinator)
    assert applies(coordinator, Category.REFERRAL_REQUEST)


def test_an_inactive_referral_listing_does_not_count():
    from referrals.models import ReferralListMember

    former = _member("aud-former@x.test", role="analyst")
    ReferralListMember.objects.create(user=former, is_active=False)
    assert not applies(former, Category.REFERRAL_REQUEST)


def test_tuition_rows_follow_owes_tuition():
    student = _member("aud-student@x.test", role="candidate")
    assert student.profile.owes_tuition
    assert applies(student, Category.TUITION_REMINDER)
    assert applies(student, Category.TUITION_PLAN_DECISION)

    analyst = _member("aud-analyst@x.test", role="analyst")
    assert not analyst.profile.owes_tuition
    assert not applies(analyst, Category.TUITION_REMINDER)
    assert not applies(analyst, Category.TUITION_PLAN_DECISION)


def test_superusers_see_everything():
    su = User.objects.create_superuser(email="aud-su@x.test", password="x")
    assert set(visible_categories(su)) == set(CATEGORY_META)


def test_visible_categories_preserves_table_order():
    user = _member("aud-order@x.test", role="analyst")
    visible = visible_categories(user)
    assert visible == [c for c in CATEGORY_META if c in set(visible)]
