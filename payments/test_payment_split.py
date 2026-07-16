"""Splitting a payment across categories — sibling rows, whole-charge
refunds, split badges (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from accounts.models import User
from payments import ledger
from payments.models import Charge, DuesPeriod, Payment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="trs@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def _member(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _dues_period():
    return DuesPeriod.objects.create(
        name="AY 2025-2026", slug="ay-2025-split",
        start_date=date(2025, 9, 1), due_date=date(2025, 9, 30),
        end_date=date(2026, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))


def _payment(user, ptype=Payment.Type.TUITION, amount="400",
             method=Payment.Method.STRIPE, intent=""):
    p = Payment.objects.create(
        user=user, payment_type=ptype, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=method,
        stripe_payment_intent_id=intent)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2026, 1, 10, 12, tzinfo=tz.utc))
    p.refresh_from_db()
    return p


def _split(client, p, parts, extra=None):
    data = {"part_type": [t for t, a, *_ in parts],
            "part_amount": [a for t, a, *_ in parts]}
    settles = [str(i) for i, part in enumerate(parts)
               if len(part) > 2 and part[2]]
    if settles:
        data["part_settle"] = settles
    if extra:
        data.update(extra)
    return client.post(reverse("treasurer_payment_split", args=[p.id]), data)


# --- the split itself --------------------------------------------------------


def test_split_creates_siblings_and_adjusts_parent(client, treasurer):
    _dues_period()
    m = _member("sp1@x.test")
    p = _payment(m, amount="400", intent="pi_split_1")
    resp = _split(client, p, [("dues", "150"), ("registration", "250")])
    assert resp.status_code == 302
    p.refresh_from_db()
    assert p.payment_type == Payment.Type.DUES
    assert p.amount == Decimal("150")
    assert p.dues_period is not None            # bound by payment date
    assert p.source == "verified"
    assert "Split" in p.notes
    child = Payment.objects.get(split_from=p)
    assert child.payment_type == Payment.Type.REGISTRATION
    assert child.amount == Decimal("250")
    assert child.user_id == m.id
    assert child.paid_at == p.paid_at
    assert child.status == Payment.Status.SUCCEEDED
    assert child.stripe_payment_intent_id == ""  # parent keeps Stripe identity
    assert f"#{p.pk}" in child.notes
    # Total money conserved.
    total = sum(x.amount for x in Payment.objects.filter(user=m))
    assert total == Decimal("400")


def test_split_with_settle_nets_to_zero(client, treasurer):
    """LaPenta-style: $400 'tuition' = $150 dues + $250 unrecorded seminar fee."""
    period = _dues_period()
    m = _member("sp2@x.test")
    from payments.charges import sync_dues_charges
    with patch("django.utils.timezone.now") as now:
        now.return_value = datetime(2026, 1, 15, tzinfo=tz.utc)
        sync_dues_charges(period)               # $100 dues charge exists
    p = _payment(m, amount="400")
    _split(client, p, [("dues", "150"), ("registration", "250", True)])
    settle = Charge.objects.get(category=Charge.Category.REGISTRATION, user=m)
    assert settle.amount == Decimal("250")
    assert settle.effective_date == date(2026, 1, 10)
    assert settle.staff_adjusted is True
    acct = ledger.member_account(m)
    # pot 400 vs charges: 100 dues + 250 settle = 350 → 50 credit (their
    # dues overpayment), NOT the 300 phantom credit a bare retype leaves.
    assert acct["credit"] == Decimal("50")


def test_split_rejects_bad_sums_and_makes_no_changes(client, treasurer):
    m = _member("sp3@x.test")
    p = _payment(m, amount="400")
    for parts in ([("dues", "150"), ("registration", "200")],   # short
                  [("dues", "150")],                            # one part
                  [("dues", "150"), ("registration", "1e999")]):
        _split(client, p, parts)
        p.refresh_from_db()
        assert p.amount == Decimal("400")
        assert Payment.objects.filter(split_from=p).count() == 0


def test_split_refusals(client, treasurer):
    m = _member("sp4@x.test")
    # memberless
    anon = _payment(None, ptype=Payment.Type.DONATION, amount="100")
    _split(client, anon, [("dues", "40"), ("donation", "60")])
    assert Payment.objects.filter(split_from=anon).count() == 0
    # already-split child cannot re-split
    p = _payment(m, amount="400")
    _split(client, p, [("dues", "150"), ("registration", "250")])
    child = Payment.objects.get(split_from=p)
    _split(client, child, [("dues", "100"), ("donation", "150")])
    assert Payment.objects.filter(split_from=child).count() == 0
    # parent cannot re-split
    _split(client, p, [("dues", "75"), ("donation", "75")])
    assert Payment.objects.filter(split_from=p).count() == 1


def test_split_away_from_tuition_unwinds_installment(client, treasurer):
    from payments.models import TuitionEnrollment, TuitionInstallment
    from payments.operations import complete_payment
    m = _member("sp5@x.test")
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026 T", slug="t-2025-split",
        start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
        decision_due_date=date(2025, 8, 31), tuition_amount=Decimal("2000"))
    enr = TuitionEnrollment.objects.create(
        user=m, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    inst = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, due_date=tp.decision_due_date,
        amount=Decimal("400"))
    p = Payment.objects.create(
        user=m, payment_type=Payment.Type.TUITION, amount=Decimal("400"),
        status=Payment.Status.PENDING, method=Payment.Method.OFFLINE,
        tuition_installment=inst)
    complete_payment(p)
    inst.refresh_from_db()
    assert inst.paid is True
    _split(client, p, [("dues", "150"), ("registration", "250")])
    inst.refresh_from_db()
    assert inst.paid is False                    # backing money left tuition
    p.refresh_from_db()
    assert p.tuition_installment_id is None


# --- whole-charge refunds ----------------------------------------------------


def test_refund_of_any_part_refunds_the_whole_family(client, treasurer):
    m = _member("sp6@x.test")
    p = _payment(m, amount="400", intent="pi_split_2")
    _split(client, p, [("dues", "150"), ("registration", "250")])
    child = Payment.objects.get(split_from=p)
    with patch("payments.refund.stripe.Refund.create") as refund:
        refund.return_value = {"id": "re_1"}
        client.post(reverse("treasurer_payment_refund", args=[child.id]))
    assert refund.call_count == 1
    assert refund.call_args.kwargs["payment_intent"] == "pi_split_2"
    p.refresh_from_db()
    child.refresh_from_db()
    assert p.status == Payment.Status.REFUNDED
    assert child.status == Payment.Status.REFUNDED
    assert "entire" in child.notes.lower() or "split" in child.notes.lower()


def test_offline_split_refund_marks_all_parts(client, treasurer):
    m = _member("sp7@x.test")
    p = _payment(m, amount="400", method=Payment.Method.OFFLINE)
    _split(client, p, [("dues", "150"), ("donation", "250")])
    client.post(reverse("treasurer_payment_refund", args=[p.id]))
    child = Payment.objects.get(split_from=p)
    p.refresh_from_db()
    assert p.status == Payment.Status.REFUNDED
    assert child.status == Payment.Status.REFUNDED


# --- visuals -----------------------------------------------------------------


def test_split_badge_and_warning_render(client, treasurer):
    m = _member("sp8@x.test")
    p = _payment(m, amount="400", intent="pi_split_3")
    _split(client, p, [("dues", "150"), ("registration", "250")])
    for url in (reverse("treasurer_payments"),
                reverse("treasurer_member_detail", args=[m.id])):
        content = client.get(url).content.decode()
        assert content.count(">split<") >= 2          # parent + child badges
        assert "entire original" in content           # refund warning copy


def test_split_button_hidden_for_ineligible_rows(client, treasurer):
    m = _member("sp9@x.test")
    _payment(m, amount="400")
    content = client.get(reverse("treasurer_payments")).content.decode()
    assert "Split" in content                          # eligible: shown
    Payment.objects.all().update(status=Payment.Status.REFUNDED)
    content = client.get(reverse("treasurer_payments")).content.decode()
    assert 'id="split-' not in content                 # refunded: hidden
