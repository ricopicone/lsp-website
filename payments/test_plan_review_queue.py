"""The Board's tuition payment-plan review queue (task #450 phase B):
``payments.views_plan_review.tuition_plan_queue`` /
``tuition_plan_decide``.

Gate: superuser OR active Board member; anonymous GET redirects to login,
signed-in non-Board 404s (``core.access.gate_or_login`` convention).
Approve moves the enrollment to PAYMENT_PLAN; decline reverts it (deletes
the PLAN_REQUESTED row) to no-decision. Both notify the applicant and are
idempotent-guarded — only a PENDING application can be decided.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from committees.models import Committee
from notifications.categories import Category
from notifications.models import Notification
from payments.models import TuitionEnrollment, TuitionPeriod, TuitionPlanApplication
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_seeded_periods():
    # A seed migration pre-populates TuitionPeriod rows; a clean slate keeps
    # these tests unambiguous.
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def period():
    return TuitionPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 1),
        tuition_amount=Decimal("1000"),
    )


@pytest.fixture
def member():
    u = User.objects.create_user(email="planqueue-member@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


@pytest.fixture
def board_member():
    u = User.objects.create_user(email="planqueue-board@x.test", password="x")
    Committee.objects.get(slug="board").add_member(
        u, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    return u


@pytest.fixture
def superuser():
    return User.objects.create_superuser(
        email="planqueue-super@x.test", password="x",
    )


@pytest.fixture
def outsider():
    return User.objects.create_user(email="planqueue-outsider@x.test", password="x")


@pytest.fixture
def application(member, period):
    TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.PLAN_REQUESTED,
    )
    return TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Reduced income this year.",
    )


# ------------------------------------------------------------------- gate ---

def test_anonymous_get_redirects_to_login(client):
    url = reverse("tuition_plan_queue")
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == f"/accounts/login/?next={url}"


def test_signed_in_non_board_404s(client, outsider):
    client.force_login(outsider)
    resp = client.get(reverse("tuition_plan_queue"))
    assert resp.status_code == 404


def test_superuser_can_reach_queue(client, superuser, application):
    client.force_login(superuser)
    resp = client.get(reverse("tuition_plan_queue"))
    assert resp.status_code == 200


def test_decide_gate_applies_to_post_too(client, outsider, application):
    client.force_login(outsider)
    resp = client.post(
        reverse("tuition_plan_decide", args=[application.pk]),
        {"action": "approve"},
    )
    assert resp.status_code == 404
    application.refresh_from_db()
    assert application.status == TuitionPlanApplication.Status.PENDING


# ------------------------------------------------------------------- list ---

def test_board_member_sees_pending_application(client, board_member, application):
    client.force_login(board_member)
    resp = client.get(reverse("tuition_plan_queue"))
    assert resp.status_code == 200
    assert list(resp.context["pending"]) == [application]
    assert list(resp.context["decided"]) == []


def test_decided_applications_are_separated_from_pending(client, board_member, member, period):
    decided = TuitionPlanApplication.objects.create(
        user=member, tuition_period=period, reasons="Already handled.",
        status=TuitionPlanApplication.Status.DECLINED,
    )
    client.force_login(board_member)
    resp = client.get(reverse("tuition_plan_queue"))
    assert list(resp.context["pending"]) == []
    assert list(resp.context["decided"]) == [decided]


# --------------------------------------------------------------- approve ---

def test_approve_flips_enrollment_and_notifies(client, board_member, member, period, application):
    client.force_login(board_member)
    resp = client.post(
        reverse("tuition_plan_decide", args=[application.pk]),
        {"action": "approve", "note": "Welcome, approved for two installments."},
    )
    assert resp.status_code == 302

    application.refresh_from_db()
    assert application.status == TuitionPlanApplication.Status.APPROVED
    assert application.decided_by == board_member
    assert application.decided_at is not None
    assert application.note == "Welcome, approved for two installments."

    enrollment = TuitionEnrollment.objects.get(user=member, tuition_period=period)
    assert enrollment.status == TuitionEnrollment.Status.PAYMENT_PLAN

    note = Notification.objects.get(recipient=member, category=Category.TUITION_PLAN_REVIEW)
    assert "approved" in note.title


def test_approve_recreates_enrollment_if_member_deleted_it(
    client, board_member, member, period, application
):
    """The enrollment row is expected to exist (PLAN_REQUESTED) but approval
    must not crash if the member's decision row is gone."""
    TuitionEnrollment.objects.filter(user=member, tuition_period=period).delete()
    client.force_login(board_member)
    resp = client.post(
        reverse("tuition_plan_decide", args=[application.pk]), {"action": "approve"},
    )
    assert resp.status_code == 302
    enrollment = TuitionEnrollment.objects.get(user=member, tuition_period=period)
    assert enrollment.status == TuitionEnrollment.Status.PAYMENT_PLAN


# --------------------------------------------------------------- decline ---

def test_decline_deletes_enrollment_and_notifies(client, board_member, member, period, application):
    client.force_login(board_member)
    resp = client.post(
        reverse("tuition_plan_decide", args=[application.pk]),
        {"action": "decline", "note": "Please choose pay-in-full or skip."},
    )
    assert resp.status_code == 302

    application.refresh_from_db()
    assert application.status == TuitionPlanApplication.Status.DECLINED
    assert application.decided_by == board_member
    assert application.note == "Please choose pay-in-full or skip."

    assert not TuitionEnrollment.objects.filter(user=member, tuition_period=period).exists()

    note = Notification.objects.get(recipient=member, category=Category.TUITION_PLAN_REVIEW)
    assert "unable to approve" in note.title
    # Provisional coverage was live while the request was pending, so the
    # decline has to mention anything registered under it (task #484).
    assert "tuition coverage" in note.body
    assert "settling" in note.body


def test_decline_leaves_enrollment_alone_if_no_longer_plan_requested(
    client, board_member, member, period, application
):
    """If the member's enrollment has moved on (e.g. they self-changed their
    decision) since requesting, decline must not delete that later row."""
    TuitionEnrollment.objects.filter(user=member, tuition_period=period).update(
        status=TuitionEnrollment.Status.COMMITTED,
    )
    client.force_login(board_member)
    client.post(
        reverse("tuition_plan_decide", args=[application.pk]), {"action": "decline"},
    )
    enrollment = TuitionEnrollment.objects.get(user=member, tuition_period=period)
    assert enrollment.status == TuitionEnrollment.Status.COMMITTED


# ----------------------------------------------------------- idempotency ---

def test_deciding_twice_is_a_noop_error(client, board_member, member, period, application):
    client.force_login(board_member)
    client.post(
        reverse("tuition_plan_decide", args=[application.pk]), {"action": "approve"},
    )
    Notification.objects.filter(recipient=member).delete()

    resp = client.post(
        reverse("tuition_plan_decide", args=[application.pk]), {"action": "decline"},
    )
    assert resp.status_code == 302

    application.refresh_from_db()
    # Still APPROVED — the second decision did not overwrite the first.
    assert application.status == TuitionPlanApplication.Status.APPROVED
    # No fresh notification fired for the no-op second attempt.
    assert not Notification.objects.filter(recipient=member).exists()
