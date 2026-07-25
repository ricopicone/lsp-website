"""Member statement actions — retype, split, settle, note (task #439).

Full treasurer parity on the member's OWN payments (own-payment scoping
enforced via ``get_object_or_404(..., user=request.user)``), with
``source=SELF_REPORTED`` and member-attributed audit notes. Mirrors the
idioms of ``test_payment_retype.py`` / ``test_payment_split.py``."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Source, User
from payments import ledger
from payments.models import (
    Charge,
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)
from payments.operations import complete_payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


@pytest.fixture
def member(client):
    u = User.objects.create_user(email="mem@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    client.force_login(u)
    return u


@pytest.fixture
def other_member():
    u = User.objects.create_user(email="other@x.test", password="x")
    u.profile.role = "candidate"
    u.profile.save()
    return u


def _tuition_period(**overrides):
    kwargs = dict(
        name="AY 2026-2027 T", slug="t-2026-my",
        start_date=date(2026, 9, 1), end_date=date(2027, 8, 31),
        decision_due_date=date(2026, 8, 31), tuition_amount=Decimal("2000"))
    kwargs.update(overrides)
    return TuitionPeriod.objects.create(**kwargs)


def _dues_period(**overrides):
    kwargs = dict(
        name="AY 2026-2027", slug="ay-2026-my",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"))
    kwargs.update(overrides)
    return DuesPeriod.objects.create(**kwargs)


def timezone_aware(d):
    from django.utils import timezone
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


def _payment(user, ptype=Payment.Type.DONATION, amount="100",
             method=Payment.Method.OFFLINE, status=Payment.Status.SUCCEEDED,
             **extra):
    p = Payment.objects.create(
        user=user, payment_type=ptype, amount=Decimal(amount),
        status=status, method=method, **extra)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2026, 10, 1, 12, tzinfo=tz.utc))
    p.refresh_from_db()
    return p


# ---------------------------------------------------------------- retype ---

def test_retype_donation_to_dues_applies_self_reported_member_note(client, member):
    """Full parity: donation flips are NOT blocked for members (unlike the
    retired my_payments_update table), and provenance/attribution differ
    from the treasurer path."""
    period = _dues_period()
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="100")

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "dues", "dues_period": str(period.id)})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.DUES
    assert payment.dues_period_id == period.id
    assert payment.source == Source.SELF_REPORTED
    assert "Donation" in payment.notes
    assert "Dues" in payment.notes
    assert f"by member {member.email}" in payment.notes


def test_retype_other_members_payment_404s_unchanged(client, member, other_member):
    payment = _payment(other_member, ptype=Payment.Type.DONATION, amount="75")

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "dues"})
    assert resp.status_code == 404
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.DONATION
    assert payment.source != Source.SELF_REPORTED


def test_retype_registration_settling_payment_refused(client, member):
    from events.models import Audience, Event, PriceTier

    event = Event.objects.create(
        title="Seminar", slug="sem-my-retype",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15))
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50"))
    registration = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("50"), status=Registration.Status.PAID)
    payment = _payment(
        member, ptype=Payment.Type.REGISTRATION, amount="50",
        registration=registration)

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "donation"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.REGISTRATION


def test_retype_split_child_allowed_for_own_row(client, member):
    """Members MAY re-categorize their own split children — deliberate
    parity delta from the treasurer split-row restriction (there is none)
    and from the retired my_payments_update table (which blocked it)."""
    parent = _payment(member, ptype=Payment.Type.TUITION, amount="400")
    child = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("150"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        split_from=parent, paid_at=parent.paid_at,
        notes=f"Split from payment #{parent.pk}")

    resp = client.post(
        reverse("my_payment_retype", args=[child.id]),
        {"payment_type": "donation"})
    assert resp.status_code == 302
    child.refresh_from_db()
    assert child.payment_type == Payment.Type.DONATION
    assert child.source == Source.SELF_REPORTED


def test_retype_to_registration_with_settle_mints_member_charge_nets_zero(client, member):
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="60")

    before = ledger.member_account(member)["paid"]
    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "registration", "settle_charge": "1"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.REGISTRATION

    charge = Charge.objects.get(user=member, category=Charge.Category.REGISTRATION)
    assert charge.amount == Decimal("60")
    assert charge.source == Source.SELF_REPORTED
    assert charge.staff_adjusted is True
    assert f"by member {member.email}" in charge.notes

    acct = ledger.member_account(member)
    after = acct["paid"]
    assert after - before == Decimal("60")  # the payment itself still counts
    # And the settlement charge nets it to zero on the ledger's balance.
    assert acct["balance"] == Decimal("0")


def test_settle_only_on_own_registration_payment_mints_charge(client, member):
    """A member can insert the matching settlement charge on their own
    already-Registration payment without re-categorizing first (task #468
    follow-up) — mirrors the treasurer capability."""
    from payments.models import PaymentMemberAction

    payment = _payment(member, ptype=Payment.Type.REGISTRATION, amount="120")
    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "registration", "settle_charge": "1"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.payment_type == Payment.Type.REGISTRATION   # unchanged

    charge = Charge.objects.get(user=member, category=Charge.Category.REGISTRATION)
    assert charge.amount == Decimal("120")
    assert charge.source == Source.SELF_REPORTED
    assert f"by member {member.email}" in charge.notes
    assert ledger.member_account(member)["balance"] == Decimal("0")
    assert PaymentMemberAction.objects.filter(
        payment=payment, action=PaymentMemberAction.Action.RETYPE).exists()


def test_retype_ay_binding_posted_tuition_period(client, member):
    period_a = _tuition_period(name="AY A", slug="t-my-a")
    period_b = _tuition_period(
        name="AY B", slug="t-my-b",
        start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
        decision_due_date=date(2025, 8, 31))
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="200")

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "tuition", "tuition_period": str(period_b.id)})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.tuition_period_id == period_b.id
    assert payment.tuition_period_id != period_a.id


def test_retype_away_from_tuition_unwinds_installment(client, member):
    period = _tuition_period()
    enr = TuitionEnrollment.objects.create(
        user=member, tuition_period=period,
        status=TuitionEnrollment.Status.COMMITTED)
    installment = TuitionInstallment.objects.create(
        enrollment=enr, sequence=1, due_date=period.decision_due_date,
        amount=Decimal("2000"))
    payment = Payment.objects.create(
        payment_type=Payment.Type.TUITION, user=member, amount=Decimal("2000"),
        method=Payment.Method.OFFLINE, tuition_period=period,
        tuition_installment=installment)
    complete_payment(payment)
    installment.refresh_from_db()
    enr.refresh_from_db()
    assert installment.paid is True
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "donation"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    installment.refresh_from_db()
    enr.refresh_from_db()
    assert payment.tuition_installment_id is None
    assert installment.paid is False
    assert installment.paid_at is None
    # Decision record untouched (do-not-over-automate); note attributed to
    # the member, not "treasurer".
    assert enr.status == TuitionEnrollment.Status.PAID_IN_FULL
    assert f"by member {member.email}" in enr.notes
    assert "unpaid again" in enr.notes


def test_noop_retype_refused(client, member):
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="100")

    resp = client.post(
        reverse("my_payment_retype", args=[payment.id]),
        {"payment_type": "donation"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.notes == ""


# ------------------------------------------------------------------ split --

def test_split_tuition_into_dues_and_settled_registration(client, member):
    period = _dues_period()
    payment = _payment(member, ptype=Payment.Type.TUITION, amount="400")

    before = ledger.member_account(member)["paid"]
    resp = client.post(
        reverse("my_payment_split", args=[payment.id]),
        {
            "part_type": ["dues", "registration"],
            "part_amount": ["150", "250"],
            "part_settle": ["1"],
            "dues_period": str(period.id),
        })
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.amount == Decimal("150")
    assert payment.payment_type == Payment.Type.DUES
    assert payment.source == Source.SELF_REPORTED

    child = Payment.objects.get(split_from=payment)
    assert child.amount == Decimal("250")
    assert child.payment_type == Payment.Type.REGISTRATION
    assert child.source == Source.SELF_REPORTED
    assert f"by member {member.email}" in child.notes

    charge = Charge.objects.get(user=member, category=Charge.Category.REGISTRATION)
    assert charge.amount == Decimal("250")
    assert charge.source == Source.SELF_REPORTED
    assert charge.staff_adjusted is True
    assert f"by member {member.email}" in charge.notes
    # The settlement charge exactly matches the settled part — that pair
    # nets to zero on the statement.
    assert charge.amount == child.amount

    after = ledger.member_account(member)["paid"]
    # Splitting only re-categorizes existing money — the total counted-paid
    # sum (150 dues + 250 registration) is unchanged, and sums exact against
    # the original $400.
    assert after == before
    assert payment.amount + child.amount == Decimal("400")


def test_split_with_donation_part_allowed(client, member):
    """Full parity: donation parts ARE allowed on the member split path."""
    payment = _payment(member, ptype=Payment.Type.TUITION, amount="300")

    resp = client.post(
        reverse("my_payment_split", args=[payment.id]),
        {
            "part_type": ["donation", "tuition"],
            "part_amount": ["100", "200"],
        })
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.amount == Decimal("100")
    assert payment.payment_type == Payment.Type.DONATION
    child = Payment.objects.get(split_from=payment)
    assert child.payment_type == Payment.Type.TUITION
    assert child.amount == Decimal("200")
    assert child.source == Source.SELF_REPORTED


def test_split_other_members_payment_404s(client, member, other_member):
    payment = _payment(other_member, ptype=Payment.Type.TUITION, amount="300")

    resp = client.post(
        reverse("my_payment_split", args=[payment.id]),
        {"part_type": ["dues", "donation"], "part_amount": ["100", "200"]})
    assert resp.status_code == 404
    assert not Payment.objects.filter(split_from=payment).exists()


def test_split_registration_settling_payment_refused(client, member):
    from events.models import Audience, Event, PriceTier

    event = Event.objects.create(
        title="Seminar", slug="sem-my-split",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15))
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50"))
    registration = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("50"), status=Registration.Status.PAID)
    payment = _payment(
        member, ptype=Payment.Type.REGISTRATION, amount="50",
        registration=registration)

    resp = client.post(
        reverse("my_payment_split", args=[payment.id]),
        {"part_type": ["dues", "donation"], "part_amount": ["25", "25"]})
    assert resp.status_code == 302
    assert not Payment.objects.filter(split_from=payment).exists()


def test_split_row_cannot_be_re_split(client, member):
    parent = _payment(member, ptype=Payment.Type.TUITION, amount="400")
    child = Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("150"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        split_from=parent, paid_at=parent.paid_at)

    resp = client.post(
        reverse("my_payment_split", args=[child.id]),
        {"part_type": ["dues", "donation"], "part_amount": ["75", "75"]})
    assert resp.status_code == 302
    assert not Payment.objects.filter(split_from=child).exists()


# ------------------------------------------------------------------- note --

def test_note_write_replace_clear_round_trip(client, member):
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="100")

    resp = client.post(
        reverse("my_payment_note", args=[payment.id]), {"note": "First note."})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.member_note == "First note."

    resp = client.post(
        reverse("my_payment_note", args=[payment.id]),
        {"note": "  Replaced note.  "})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.member_note == "Replaced note."  # replaced, not appended

    resp = client.post(reverse("my_payment_note", args=[payment.id]), {"note": ""})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.member_note == ""


def test_note_capped_at_1000_chars(client, member):
    payment = _payment(member, ptype=Payment.Type.DONATION, amount="100")
    long_note = "x" * 1500

    client.post(reverse("my_payment_note", args=[payment.id]), {"note": long_note})
    payment.refresh_from_db()
    assert len(payment.member_note) == 1000


def test_note_other_members_payment_404s(client, member, other_member):
    payment = _payment(other_member, ptype=Payment.Type.DONATION, amount="100")

    resp = client.post(
        reverse("my_payment_note", args=[payment.id]), {"note": "sneaky"})
    assert resp.status_code == 404
    payment.refresh_from_db()
    assert payment.member_note == ""
