"""Tests for the dues lifecycle: periods, reminders, treasurer dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from payments.dues import is_dues_obligated
from payments.models import DuesPeriod, DuesReminder, Payment


@pytest.fixture
def current_period(db):
    """Return the DuesPeriod containing today.

    The seed migration creates the AY containing today, so this should
    always exist. If the seed picked a future-only period (e.g. tests run
    just before Sep 1), synthesize one covering today.
    """
    period = DuesPeriod.current()
    if period is not None:
        return period
    today = timezone.now().date()
    return DuesPeriod.objects.create(
        name="Test AY",
        slug="test-ay",
        start_date=today - timedelta(days=60),
        due_date=today - timedelta(days=30),
        end_date=today + timedelta(days=300),
        dues_amount_pre_candidate=Decimal("50.00"),
        dues_amount_candidate=Decimal("100.00"),
        dues_amount_analyst=Decimal("150.00"),
    )


@pytest.fixture
def member(db):
    """A dues-obligated user. Uses CANDIDATE role — MEMBER is no longer in
    DUES_OBLIGATED_ROLES (members are captured by in-training + analyst /
    scholar roles in practice)."""
    u = User.objects.create_user(email="member@example.com")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.save()
    return u


@pytest.fixture
def external_user(db):
    u = User.objects.create_user(email="external@example.com")
    u.profile.role = Profile.Role.EXTERNAL
    u.profile.save()
    return u


@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    monkeypatch.setattr(
        "payments.views.create_dues_session",
        MagicMock(return_value=MagicMock(id="cs_test", url="https://stripe.test/dues")),
    )


# ---- DuesPeriod.current() ---------------------------------------------


@pytest.mark.django_db
def test_current_finds_period_containing_today(current_period):
    inside = current_period.start_date + timedelta(days=30)
    assert DuesPeriod.current(on_date=inside) == current_period


@pytest.mark.django_db
def test_current_returns_none_when_no_period_covers_date():
    long_after = date(2030, 1, 1)
    assert DuesPeriod.current(on_date=long_after) is None


# ---- is_dues_obligated --------------------------------------------------


def test_candidate_role_is_obligated(member):
    """The ``member`` fixture is now a CANDIDATE — the in-training / analyst /
    scholar roles are the dues-obligated set."""
    assert is_dues_obligated(member) is True


def test_external_role_not_obligated(external_user):
    assert is_dues_obligated(external_user) is False


def test_anonymous_not_obligated():
    from django.contrib.auth.models import AnonymousUser
    assert is_dues_obligated(AnonymousUser()) is False


# ---- /dues/ view uses current period ----------------------------------


def test_dues_page_shows_current_period_amount_and_due_date(
    client, member, current_period,
):
    client.force_login(member)
    response = client.get(reverse("dues"))
    assert response.status_code == 200
    assert bytes(current_period.name, "utf-8") in response.content
    assert b"100.00" in response.content


def test_dues_post_attaches_period_to_payment(client, member, current_period):
    client.force_login(member)
    client.post(reverse("dues"))
    payment = Payment.objects.get(payment_type=Payment.Type.DUES, user=member)
    assert payment.dues_period == current_period


def test_dues_page_shows_already_paid_when_user_has_succeeded_payment(
    client, member, current_period,
):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member,
        amount=current_period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=current_period,
    )
    client.force_login(member)
    response = client.get(reverse("dues"))
    assert response.status_code == 200
    assert b"paid up" in response.content
    # No Stripe redirect — confirm button isn't on the already-paid page.
    assert b"Continue to payment" not in response.content


# ---- Landing banner ---------------------------------------------------


def test_landing_shows_banner_for_obligated_unpaid_member(
    client, member, current_period,
):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    client.force_login(member)
    response = client.get(reverse("core:landing"))
    assert b"outstanding balance" in response.content.lower()


def test_landing_no_banner_for_external_user(client, external_user, current_period):
    client.force_login(external_user)
    response = client.get(reverse("core:landing"))
    assert b"outstanding balance" not in response.content.lower()


def test_landing_no_banner_when_paid(client, member, current_period):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member,
        amount=current_period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=current_period,
    )
    client.force_login(member)
    response = client.get(reverse("core:landing"))
    assert b"outstanding balance" not in response.content.lower()


# ---- send_dues_reminders command --------------------------------------


def _set_period_due_in_past(period):
    """Pretend the period's due date is in the past so reminders fire."""
    period.due_date = timezone.now().date() - timedelta(days=7)
    period.save(update_fields=("due_date",))


@pytest.mark.django_db
def test_reminders_skipped_before_due_date(member, current_period):
    # Make sure due_date is in the future for this test.
    current_period.due_date = timezone.now().date() + timedelta(days=30)
    current_period.save()
    out = StringIO()
    call_command("send_dues_reminders", stdout=out)
    assert b"not yet past due" in out.getvalue().encode() or "not yet past due" in out.getvalue()
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_reminders_sent_to_obligated_unpaid_member(member, current_period):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    _set_period_due_in_past(current_period)
    out = StringIO()
    call_command("send_dues_reminders", stdout=out)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["member@example.com"]
    assert "dues are due" in mail.outbox[0].subject
    assert DuesReminder.objects.filter(user=member, dues_period=current_period).count() == 1


@pytest.mark.django_db
def test_reminders_skip_user_with_recent_reminder(member, current_period):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    _set_period_due_in_past(current_period)
    DuesReminder.objects.create(user=member, dues_period=current_period)
    call_command("send_dues_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0
    # Throttle log unchanged
    assert DuesReminder.objects.filter(user=member).count() == 1


@pytest.mark.django_db
def test_reminders_skip_paid_user(member, current_period):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    _set_period_due_in_past(current_period)
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member,
        amount=current_period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=current_period,
    )
    call_command("send_dues_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0
    assert DuesReminder.objects.filter(user=member).count() == 0


@pytest.mark.django_db
def test_reminders_skip_unminted_charge(member, current_period):
    """No dues charge minted for the member yet → dues_state is None →
    nothing to chase, even though the member is obligated (task #439)."""
    _set_period_due_in_past(current_period)
    call_command("send_dues_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0
    assert DuesReminder.objects.filter(user=member).count() == 0


@pytest.mark.django_db
def test_reminders_skip_non_obligated_roles(external_user, current_period):
    _set_period_due_in_past(current_period)
    call_command("send_dues_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_reminders_dry_run_sends_nothing_and_logs_nothing(member, current_period):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    _set_period_due_in_past(current_period)
    call_command("send_dues_reminders", "--dry-run", stdout=StringIO())
    assert len(mail.outbox) == 0
    assert DuesReminder.objects.count() == 0


@pytest.mark.django_db
def test_reminder_resumes_after_seven_days(member, current_period):
    """A reminder older than 7 days no longer blocks a fresh send."""
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)  # mint the ledger charge for member
    _set_period_due_in_past(current_period)
    old = DuesReminder.objects.create(user=member, dues_period=current_period)
    DuesReminder.objects.filter(pk=old.pk).update(
        sent_at=timezone.now() - timedelta(days=8),
    )
    call_command("send_dues_reminders", stdout=StringIO())
    assert len(mail.outbox) == 1


# ---- create_dues_period_if_needed command -----------------------------


@pytest.mark.django_db
def test_create_dues_period_skips_when_current_and_next_exist(current_period):
    """If both current AY and next AY exist, the command makes no changes."""
    # Pre-create the next AY so the always-two-ahead invariant is satisfied.
    next_start = current_period.start_date.year + 1
    DuesPeriod.objects.create(
        name=f"AY {next_start}-{next_start + 1}",
        slug=f"ay-{next_start}-{next_start + 1}",
        start_date=date(next_start, 9, 1),
        due_date=date(next_start, 10, 1),
        end_date=date(next_start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50.00"),
        dues_amount_candidate=Decimal("100.00"),
        dues_amount_analyst=Decimal("150.00"),
    )
    out = StringIO()
    before = DuesPeriod.objects.count()
    call_command("create_dues_period_if_needed", stdout=out)
    assert DuesPeriod.objects.count() == before
    # Both periods should report "exists; skipping".
    assert out.getvalue().count("skipping") == 2


@pytest.mark.django_db
def test_create_dues_period_inherits_amount_from_last(current_period):
    """The newly-created next AY inherits its tiers + cadence from the prior."""
    # Mutate current_period so we can verify inheritance carries the changes.
    current_period.dues_amount_pre_candidate = Decimal("55.55")
    current_period.dues_amount_candidate     = Decimal("111.11")
    current_period.dues_amount_analyst       = Decimal("222.22")
    current_period.reminder_interval_days    = 21
    current_period.save()

    call_command("create_dues_period_if_needed", stdout=StringIO())

    # After the command, current + next should both exist; the next AY is
    # the one we want to assert inheritance on.
    next_period = DuesPeriod.objects.order_by("-start_date").first()
    assert next_period.start_date.year == current_period.start_date.year + 1
    assert next_period.start_date.month == 9 and next_period.start_date.day == 1
    assert next_period.dues_amount_pre_candidate == Decimal("55.55")
    assert next_period.dues_amount_candidate     == Decimal("111.11")
    assert next_period.dues_amount_analyst       == Decimal("222.22")
    assert next_period.reminder_interval_days    == 21


# ---- Treasurer dashboard ----------------------------------------------


@pytest.fixture
def staff_user(db):
    u = User.objects.create_user(email="staff@example.com", password="x")
    u.is_staff = True
    u.save()
    return u


def test_treasurer_dashboard_anonymous_redirects(client):
    response = client.get(reverse("treasurer"))
    assert response.status_code == 302


def test_treasurer_dashboard_non_staff_forbidden(client, member):
    client.force_login(member)
    response = client.get(reverse("treasurer"))
    assert response.status_code == 302


def test_treasurer_dashboard_renders_for_staff(
    client, staff_user, current_period, member,
):
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member,
        amount=current_period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=current_period,
    )
    client.force_login(staff_user)
    response = client.get(reverse("treasurer"))
    assert response.status_code == 200
    assert b"Treasurer Admin" in response.content
    assert bytes(current_period.name, "utf-8") in response.content
    # Total collected reflects the one paid Payment.
    assert b"$100.00" in response.content


def test_treasurer_accounts_lists_unpaid_obligated_members_after_sync(
    client, staff_user, current_period, member,
):
    """member is obligated but hasn't paid → the synced dues charge shows them
    owing on the unified Accounts tab (task #439 — obligation now flows
    through a materialized Charge, not a role projection)."""
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)
    client.force_login(staff_user)
    response = client.get(reverse("treasurer_accounts") + "?balance=owing")
    assert b"member@example.com" in response.content


def test_treasurer_accounts_excludes_paid_from_owing_filter(
    client, staff_user, current_period, member,
):
    from payments.charges import sync_dues_charges

    sync_dues_charges(current_period)
    Payment.objects.create(
        payment_type=Payment.Type.DUES,
        user=member,
        amount=current_period.amount_for_role("candidate"),
        status=Payment.Status.SUCCEEDED,
        dues_period=current_period,
    )
    client.force_login(staff_user)
    response = client.get(reverse("treasurer_accounts") + "?balance=owing")
    # member paid → not in the owing filter.
    assert b"member@example.com" not in response.content
    # Still visible on the full roster, just squared up.
    full = client.get(reverse("treasurer_accounts"))
    assert b"member@example.com" in full.content


def test_treasurer_dashboard_excludes_external_users_from_obligated_count(
    client, staff_user, current_period, external_user,
):
    client.force_login(staff_user)
    response = client.get(reverse("treasurer"))
    # External user shouldn't appear in unpaid list.
    assert b"external@example.com" not in response.content


def test_dues_sync_then_accounts_outstanding_sums_unpaid_at_tier(current_period):
    """dues_outstanding (on the unified Accounts total) = unpaid obligated
    members × their tier rate, once their dues charges are synced."""
    from payments import ledger
    from payments.charges import sync_dues_charges

    cand = User.objects.create_user(email="c1@example.com")
    cand.profile.role = Profile.Role.CANDIDATE  # $100 tier
    cand.profile.save()
    analyst = User.objects.create_user(email="a1@example.com")
    analyst.profile.role = Profile.Role.ANALYST  # $150 tier
    analyst.profile.save()
    sync_dues_charges(current_period)
    # Nobody paid → outstanding should include both at their tiers.
    rows = ledger.accounts_overview()
    total_owed = sum((r["owes"] for r in rows), Decimal("0"))
    assert total_owed >= Decimal("250")  # 100 + 150 (+ any other obligated)


@override_settings(DUES_OBLIGATED_ROLES=["analyst"])
def test_dues_sync_respects_obligated_roles_setting(
    client, staff_user, current_period, external_user,
):
    """With DUES_OBLIGATED_ROLES=[analyst], only analysts get a synced dues
    charge — and so only they appear owing on Accounts."""
    from payments.charges import sync_dues_charges

    analyst = User.objects.create_user(email="analyst-x@example.com")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.save()
    candidate = User.objects.create_user(email="cand@example.com")
    candidate.profile.role = Profile.Role.CANDIDATE
    candidate.profile.save()
    sync_dues_charges(current_period)
    client.force_login(staff_user)
    response = client.get(reverse("treasurer_accounts") + "?balance=owing")
    assert b"analyst-x@example.com" in response.content
    assert b"cand@example.com" not in response.content


# ---- Standing exempts from dues obligation -----------------------------


def test_on_leave_member_not_dues_obligated(member):
    """A dues-obligated role on non-active standing is exempt."""
    assert is_dues_obligated(member) is True  # active candidate
    member.profile.standing = Profile.Standing.ON_LEAVE
    member.profile.save()
    assert is_dues_obligated(member) is False
    member.profile.standing = Profile.Standing.RESIGNED
    member.profile.save()
    assert is_dues_obligated(member) is False
    member.profile.standing = Profile.Standing.EMERITUS
    member.profile.save()
    assert is_dues_obligated(member) is False


def test_dues_sync_excludes_on_leave(current_period):
    """The dues-charge sync (and so the treasurer's owing lists) excludes
    on-leave members — ``obligated_users_qs`` filters on ACTIVE standing."""
    from payments.charges import sync_dues_charges
    from payments.models import Charge

    active = User.objects.create_user(email="active@x.test")
    active.profile.role = Profile.Role.CANDIDATE
    active.profile.save()
    leave = User.objects.create_user(email="leave@x.test")
    leave.profile.role = Profile.Role.CANDIDATE
    leave.profile.standing = Profile.Standing.ON_LEAVE
    leave.profile.save()

    sync_dues_charges(current_period)
    assert Charge.objects.filter(user=active, category=Charge.Category.DUES).exists()
    assert not Charge.objects.filter(user=leave, category=Charge.Category.DUES).exists()


def test_landing_banner_hidden_for_on_leave(client, member, current_period):
    member.profile.standing = Profile.Standing.ON_LEAVE
    member.profile.save()
    client.force_login(member)
    response = client.get(reverse("core:landing"))
    assert b"outstanding balance" not in response.content.lower()
