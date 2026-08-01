"""Who gets emailed when a member applies for a tuition payment plan
(task #491).

The Board keeps the queue and the decision, but only the Treasurer is
emailed per application; the rest of the Board gets the bell row. Both
sides can still change it on the notification settings page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import User
from committees.models import Committee
from core.models import StaffRole
from notifications.categories import Category, EmailDelivery
from notifications.models import Notification, NotificationPreference
from payments.models import TuitionPeriod, TuitionPlanApplication
from payments.notifications import notify_plan_application_submitted
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_seeded_periods():
    TuitionPeriod.objects.all().delete()


@pytest.fixture
def period():
    return TuitionPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), end_date=date(2027, 6, 30),
        decision_due_date=date(2026, 10, 1),
        tuition_amount=Decimal("1000"),
    )


def _board(user):
    Committee.objects.get(slug="board").add_member(
        user, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    return user


@pytest.fixture
def treasurer():
    u = _board(User.objects.create_user(email="plan-treasurer@x.test", password="x"))
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.add(u)
    return u


@pytest.fixture
def board_member():
    return _board(User.objects.create_user(email="plan-board@x.test", password="x"))


@pytest.fixture
def application(period):
    applicant = User.objects.create_user(email="plan-applicant@x.test", password="x")
    applicant.profile.role = "candidate"
    applicant.profile.save()
    return TuitionPlanApplication.objects.create(
        user=applicant, tuition_period=period, reasons="Money is tight this year.",
    )


def test_treasurer_is_emailed_and_the_rest_of_the_board_is_not(
    treasurer, board_member, application, mailoutbox,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    # Both see it in the bell.
    for user in (treasurer, board_member):
        assert Notification.objects.filter(
            recipient=user, category=Category.TUITION_PLAN_REVIEW,
        ).exists()

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {treasurer.email}


def test_a_board_member_can_opt_into_the_email(
    treasurer, board_member, application, mailoutbox,
    django_capture_on_commit_callbacks,
):
    pref = NotificationPreference.objects.create(user=board_member)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {treasurer.email, board_member.email}


def test_the_treasurer_can_opt_out(
    treasurer, application, mailoutbox, django_capture_on_commit_callbacks,
):
    pref = NotificationPreference.objects.create(user=treasurer)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.OFF)
    pref.save()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    assert mailoutbox == []


def test_with_no_treasurer_the_board_is_emailed(
    board_member, application, mailoutbox, django_capture_on_commit_callbacks,
):
    # An unassigned role must never mean an application sits unseen.
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.clear()

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    recipients = {addr for m in mailoutbox for addr in m.to}
    assert recipients == {board_member.email}


def test_the_applicant_is_not_notified_as_a_reviewer(
    treasurer, application, mailoutbox, django_capture_on_commit_callbacks,
):
    _board(application.user)

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_submitted(application)

    assert not Notification.objects.filter(
        recipient=application.user, category=Category.TUITION_PLAN_REVIEW,
    ).exists()


def test_the_applicant_hears_the_decision_even_with_review_email_off(
    application, mailoutbox, django_capture_on_commit_callbacks,
):
    """The reviewer queue and the applicant's own outcome are separate
    categories — silencing the queue must not silence the applicant."""
    from payments.notifications import notify_plan_application_decided

    pref = NotificationPreference.objects.create(user=application.user)
    pref.set(Category.TUITION_PLAN_REVIEW, in_app=True, email=EmailDelivery.OFF)
    pref.save()

    application.status = TuitionPlanApplication.Status.APPROVED
    application.save(update_fields=["status"])

    with django_capture_on_commit_callbacks(execute=True):
        notify_plan_application_decided(application)

    row = Notification.objects.get(
        recipient=application.user, category=Category.TUITION_PLAN_DECISION,
    )
    assert "approved" in row.title.lower()
    assert [addr for m in mailoutbox for addr in m.to] == [application.user.email]


def test_settings_page_shows_each_member_their_true_default(client, treasurer, board_member):
    """The page reads the same resolve() dispatch uses, so a role-sensitive
    default is displayed honestly rather than as a static category default."""
    from notifications.preferences import resolve

    for user, expected in ((treasurer, "immediate"), (board_member, "off")):
        assert resolve(user, Category.TUITION_PLAN_REVIEW).email_mode == expected

        client.force_login(user)
        html = client.get("/notifications/settings/").content.decode()
        select = html.split('name="tuition_plan_review__email"', 1)[1].split("</select>", 1)[0]
        selected = [
            line for line in select.splitlines() if "selected" in line
        ]
        assert len(selected) == 1
        assert f'value="{expected}"' in selected[0]
