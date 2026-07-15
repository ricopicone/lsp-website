"""Member account page: statement + add/adjust/waive/void + record payment (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Charge, DuesPeriod, Payment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr2@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def member():
    u = User.objects.create_user(email="ma@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def test_member_page_shows_statement_and_tiles(client, treasurer, member):
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2026, 9, 1))
    resp = client.get(reverse("treasurer_member_detail", args=[member.id]))
    assert resp.status_code == 200
    assert b"Statement" in resp.content
    assert resp.context["acct"]["owes"] == Decimal("100")


def test_add_charge(client, treasurer, member):
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "75", "effective_date": "2026-09-01",
         "note": "Prorated half-year."})
    assert resp.status_code == 302
    c = Charge.objects.get(user=member)
    assert c.amount == Decimal("75")
    assert c.staff_adjusted is True
    assert "Prorated half-year." in c.notes
    assert "tr2@x.test" in c.notes


def test_add_charge_rejects_bad_amount(client, treasurer, member):
    client.post(reverse("treasurer_charge_add", args=[member.id]),
                {"category": "dues", "amount": "-5", "effective_date": "2026-09-01"})
    assert Charge.objects.count() == 0


def test_add_charge_rejects_out_of_range_amount(client, treasurer, member):
    """A huge exponent must be rejected cleanly, not 500 at save-time."""
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "1e999", "effective_date": "2026-09-01"})
    assert resp.status_code == 302
    assert Charge.objects.count() == 0


def test_add_charge_rejects_sub_cent_amount(client, treasurer, member):
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100.555", "effective_date": "2026-09-01"})
    assert resp.status_code == 302
    assert Charge.objects.count() == 0


def test_add_dues_charge_binds_period_no_sync_double_mint(client, treasurer, member):
    """A manual dues charge must bind the period FK — the minting sync keys
    idempotency on (user, dues_period), so a period-less manual charge would
    get double-minted by the next rollover/Sync click (task #439 fix 3)."""
    from django.utils import timezone

    from payments import charges as charges_mod
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100", "dues_period": str(period.id)})
    assert resp.status_code == 302
    c = Charge.objects.get(user=member)
    assert c.dues_period_id == period.id
    assert c.effective_date == period.start_date
    minted = charges_mod.sync_dues_charges(period)
    assert minted == 0
    assert Charge.objects.filter(
        user=member, category=Charge.Category.DUES).count() == 1


def test_add_dues_charge_defaults_to_current_period(client, treasurer, member):
    """No explicit period posted -> falls back to the current DuesPeriod."""
    from django.utils import timezone
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100"})
    c = Charge.objects.get(user=member)
    assert c.dues_period_id == period.id


def test_add_dues_charge_duplicate_period_rejected(client, treasurer, member):
    from django.contrib.messages import get_messages
    from django.utils import timezone
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100", "dues_period": str(period.id)})
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100", "dues_period": str(period.id)})
    assert Charge.objects.filter(
        user=member, category=Charge.Category.DUES).count() == 1
    msgs = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("already exists" in m for m in msgs)


def test_add_dues_charge_shows_in_dues_state(client, treasurer, member):
    from django.utils import timezone

    from payments import ledger
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "dues", "amount": "100", "dues_period": str(period.id)})
    acct = ledger.member_account(member)
    assert acct["dues_state"] == "unpaid"


def test_add_tuition_charge_binds_period_and_rejects_duplicate(client, treasurer, member):
    from django.contrib.messages import get_messages
    period = TuitionPeriod.objects.create(
        name="AY 2026-2027 T", slug="t-2026-add",
        start_date=date(2026, 9, 1), end_date=date(2027, 8, 31),
        decision_due_date=date(2026, 8, 31), tuition_amount=Decimal("2000"))
    resp = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "tuition", "amount": "500", "tuition_period": str(period.id)})
    assert resp.status_code == 302
    c = Charge.objects.get(user=member)
    assert c.tuition_period_id == period.id
    assert c.effective_date == period.start_date
    resp2 = client.post(
        reverse("treasurer_charge_add", args=[member.id]),
        {"category": "tuition", "amount": "500", "tuition_period": str(period.id)})
    assert Charge.objects.filter(
        user=member, category=Charge.Category.TUITION).count() == 1
    msgs = [str(m) for m in get_messages(resp2.wsgi_request)]
    assert any("already exists" in m for m in msgs)


def test_waive_void_adjust_reopen(client, treasurer, member):
    c = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2026, 9, 1))
    url = reverse("treasurer_charge_update", args=[c.id])
    client.post(url, {"action": "waive"})
    c.refresh_from_db()
    assert c.status == Charge.Status.WAIVED and c.staff_adjusted
    client.post(url, {"action": "reopen"})
    c.refresh_from_db()
    assert c.status == Charge.Status.OPEN
    client.post(url, {"action": "adjust", "amount": "80"})
    c.refresh_from_db()
    assert c.amount == Decimal("80")
    client.post(url, {"action": "void"})
    c.refresh_from_db()
    assert c.status == Charge.Status.VOID
    assert c.notes.count("tr2@x.test") == 4  # every action audited


def test_charge_update_rejects_adjust_on_waived(client, treasurer, member):
    """Status gating (task #439 fix 4b): adjust/waive only from OPEN, void
    from OPEN or WAIVED, reopen only from WAIVED (reopening VOID risks the
    partial-unique constraint on (user, period))."""
    from django.contrib.messages import get_messages
    c = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100"),
        effective_date=date(2026, 9, 1), status=Charge.Status.WAIVED)
    resp = client.post(
        reverse("treasurer_charge_update", args=[c.id]),
        {"action": "adjust", "amount": "80"})
    c.refresh_from_db()
    assert c.amount == Decimal("100")  # unchanged
    assert c.status == Charge.Status.WAIVED  # unchanged
    msgs = [str(m) for m in get_messages(resp.wsgi_request)]
    assert any("open" in m.lower() for m in msgs)


def test_record_offline_dues_payment(client, treasurer, member):
    from django.utils import timezone
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    DuesPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"ay-{start}-{start + 1}",
        start_date=date(start, 9, 1), due_date=date(start, 9, 30),
        end_date=date(start + 1, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    resp = client.post(
        reverse("treasurer_record_payment", args=[member.id]),
        {"category": "dues", "amount": "100"})
    assert resp.status_code == 302
    p = Payment.objects.get(user=member)
    assert p.status == Payment.Status.SUCCEEDED
    assert p.method == Payment.Method.OFFLINE
    assert p.dues_period is not None
    assert hasattr(p, "receipt")


def test_record_offline_tuition_payment_flips_enrollment(client, treasurer, member):
    from django.utils import timezone

    from payments.models import TuitionEnrollment
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
    client.post(reverse("treasurer_record_payment", args=[member.id]),
                {"category": "tuition", "amount": "2000"})
    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL


def test_record_offline_partial_tuition_payment_does_not_flip_enrollment(
        client, treasurer, member):
    """A partial offline tuition payment (less than the year's full rate)
    must not flip the enrollment to PAID_IN_FULL — that mislabels the
    decision record and grants covered-tier event access (task #439 fix 2).
    No installment should be minted (installments drive the paid-in-full
    check), and the payment should still succeed with a receipt."""
    from django.utils import timezone

    from payments.models import Payment, TuitionEnrollment, TuitionInstallment
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
    resp = client.post(reverse("treasurer_record_payment", args=[member.id]),
                        {"category": "tuition", "amount": "50"})
    assert resp.status_code == 302
    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.COMMITTED
    assert TuitionInstallment.objects.filter(enrollment=enr).count() == 0
    assert "tr2@x.test" in enr.notes
    assert "partial offline tuition payment of $50" in enr.notes
    p = Payment.objects.get(user=member)
    assert p.status == Payment.Status.SUCCEEDED
    assert p.tuition_installment_id is None
    assert hasattr(p, "receipt")


def test_record_offline_partial_tuition_payment_preserves_skipping_status(
        client, treasurer, member):
    """A partial payment must not overwrite an explicit prior decision like
    SKIPPING — only a full payment forces COMMITTED."""
    from django.utils import timezone

    from payments.models import TuitionEnrollment
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING)
    client.post(reverse("treasurer_record_payment", args=[member.id]),
                {"category": "tuition", "amount": "50"})
    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.SKIPPING
    assert "partial offline tuition payment of $50" in enr.notes


def test_record_tuition_payment_over_skipping_appends_audit_note(
        client, treasurer, member):
    """Flipping an explicit SKIPPING decision must leave an audit trail."""
    from django.utils import timezone

    from payments.models import TuitionEnrollment
    y = timezone.now().date().year
    start = y if timezone.now().date().month >= 9 else y - 1
    period = TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1} T", slug=f"t-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.SKIPPING)
    client.post(reverse("treasurer_record_payment", args=[member.id]),
                {"category": "tuition", "amount": "2000"})
    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert "tr2@x.test" in enr.notes
    assert "Skipping" in enr.notes  # records what the status was changed from
