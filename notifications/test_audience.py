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


def _settings_html(client, user):
    client.force_login(user)
    return client.get("/notifications/settings/").content.decode()


def test_settings_page_hides_the_board_row_from_a_plain_member(client):
    plain = _member("aud-page-plain@x.test", role="analyst")
    html = _settings_html(client, plain)
    assert "tuition_plan_review__email" not in html
    # A category everyone has is still there.
    assert "parletre_mention__email" in html


def test_settings_page_shows_the_board_row_to_a_board_member(client):
    board = _member("aud-page-board@x.test", role="analyst")
    Committee.objects.get(slug="board").add_member(
        board, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    assert "tuition_plan_review__email" in _settings_html(client, board)


def test_saving_does_not_wipe_a_hidden_categorys_stored_preference(client):
    """The POST loop must skip what the page didn't render — otherwise a
    missing checkbox reads as 'off' and silently kills the bell."""
    from notifications.categories import EmailDelivery
    from notifications.models import NotificationPreference

    plain = _member("aud-page-keep@x.test", role="analyst")
    pref = NotificationPreference.objects.create(user=plain)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    client.force_login(plain)
    resp = client.post("/notifications/settings/", {
        "digest_cadence": "weekly",
        "parletre_mention__in_app": "on",
        "parletre_mention__email": "immediate",
    })
    assert resp.status_code == 302

    stored = NotificationPreference.objects.get(user=plain).overrides
    assert stored[Category.TUITION_PLAN_REVIEW] == {
        "in_app": True, "email": "immediate",
    }
    # What the member *could* see still saved.
    assert stored[Category.PARLETRE_MENTION]["email"] == "immediate"


def test_an_empty_section_disappears(client):
    """A member who is neither on the referral list nor the coordinator has no
    Referrals row, so the whole section is gone."""
    plain = _member("aud-page-noref@x.test", role="analyst")
    assert "Referrals" not in _settings_html(client, plain)
