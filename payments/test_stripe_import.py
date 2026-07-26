"""Tests for the historical Stripe importer (logic only — no network)."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest

from accounts.models import Profile, Source, User
from payments.management.commands.import_stripe_payments import Command
from payments.models import Payment
from payments.stripe_import import (
    apply_plan,
    classify_type,
    normalize_charge,
    plan_charges,
    tag_for,
)

pytestmark = pytest.mark.django_db

# 1700000000 → 2023-11-14 UTC
TS = 1700000000
DAY = datetime.fromtimestamp(TS, tz=dt_timezone.utc)


def _charge(cid="ch_1", amount=15000, email="ann@x.test", name="Ann Lee",
            pi="pi_1", status="succeeded", paid=True, refunded=False,
            amount_refunded=0, description="", created=TS):
    return {
        "id": cid, "amount": amount, "currency": "usd", "created": created,
        "status": status, "paid": paid, "refunded": refunded,
        "amount_refunded": amount_refunded,
        "billing_details": {"email": email, "name": name},
        "receipt_email": None, "customer": None,
        "payment_intent": pi, "description": description,
    }


def _user(email, first="Ann", last="Lee"):
    return User.objects.create_user(email=email, password="x",
                                    first_name=first, last_name=last)


def _plan(charges, *, sessions=None, default_type=None, allow_overlaps=False,
          sweep_unknown=False, sweep_min=25.0):
    rows = [normalize_charge(c, sessions_by_pi=sessions or {}) for c in charges]
    ctx = Command().build_context(
        default_type, sweep_unknown=sweep_unknown, sweep_min=sweep_min,
    )
    return plan_charges(rows, ctx, allow_overlaps=allow_overlaps)


# ---- normalization & classification ---------------------------------------

def test_normalize_charge():
    row = normalize_charge(_charge(amount=15000, description="Dues 2023"))
    assert row.amount == Decimal("150.00")
    assert row.currency == "usd"
    assert row.created == DAY
    assert row.email == "ann@x.test" and row.name == "Ann Lee"
    assert row.payment_intent == "pi_1"


def test_normalize_links_session():
    sessions = {"pi_1": {"id": "cs_9", "payment_intent": "pi_1",
                         "metadata": {"payment_id": "42", "payment_type": "registration"}}}
    row = normalize_charge(_charge(), sessions_by_pi=sessions)
    assert row.checkout_session_id == "cs_9"
    assert row.session_payment_id == "42"
    assert row.session_payment_type == "registration"


def test_classify_type():
    valid = set(Payment.Type.values)
    assert classify_type(normalize_charge(_charge(description="Annual dues")), valid) == "dues"
    assert classify_type(normalize_charge(_charge(description="Tuition 1st")), valid) == "tuition"
    assert classify_type(normalize_charge(_charge(description="Gift to LSP")), valid) == "donation"
    assert classify_type(normalize_charge(_charge(description="opaque")), valid) is None


# ---- create bucket --------------------------------------------------------

def test_create_matched_by_email():
    _user("ann@x.test")
    plans = _plan([_charge(description="Annual dues")])
    assert plans[0].action == "create"
    assert plans[0].member_match == "email"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.amount == Decimal("150.00")
    assert p.status == Payment.Status.SUCCEEDED
    assert p.method == Payment.Method.STRIPE
    assert p.source == Source.STRIPE
    assert p.payment_type == Payment.Type.DUES
    assert p.user is not None
    assert p.paid_at == DAY
    assert tag_for("ch_1") in p.notes


def test_create_unmatched_member():
    plans = _plan([_charge(email="nobody@x.test", name="Zzz Nobody",
                           description="donation")])
    assert plans[0].action == "create_unmatched"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.user_id is None and p.email == "nobody@x.test"
    assert "unmatched payer" in p.notes


def test_needs_type_when_uninferable():
    _user("ann@x.test")
    # $77 is not a dues tier, tuition amount, or keyword — genuinely unknown.
    plans = _plan([_charge(amount=7700, description="mystery")])
    assert plans[0].action == "needs_type"
    apply_plan(plans)
    assert not Payment.objects.filter(stripe_payment_intent_id="pi_1").exists()


def test_default_type_sweeps_unknown():
    _user("ann@x.test")
    plans = _plan([_charge(amount=7700, description="mystery")], default_type="donation")
    assert plans[0].action == "create"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.payment_type == Payment.Type.DONATION
    assert "type defaulted" in p.notes


# ---- amount-based type inference ------------------------------------------

def test_amount_infers_dues_tier():
    _user("ann@x.test")
    # $150 with no description → standard analyst/scholar dues tier.
    plans = _plan([_charge(amount=15000, description="")])
    assert plans[0].action == "create"
    assert plans[0].payment_type == "dues"
    assert plans[0].type_inferred


def test_amount_infers_tuition_from_period():
    from datetime import date

    from payments.models import TuitionPeriod
    TuitionPeriod.objects.create(
        start_date=date(2023, 9, 1), decision_due_date=date(2023, 10, 1),
        end_date=date(2024, 8, 31), tuition_amount=Decimal("2500.00"),
    )
    _user("ann@x.test")
    plans = _plan([_charge(amount=250000, description="")])  # $2500, AY 2023
    assert plans[0].action == "create"
    assert plans[0].payment_type == "tuition"


def _tenure(user, role, start_ay=2023, end_ay=None):
    from accounts.models import MembershipTenure
    MembershipTenure.objects.create(
        user=user, role=role, standing=Profile.Standing.ACTIVE,
        start_ay=start_ay, end_ay=end_ay, source=Source.IMPORTED,
    )


def _in_training(user, **kw):
    _tenure(user, Profile.Role.PRE_CANDIDATE, **kw)


def test_multiple_charges_in_ay_are_tuition_installments():
    u = _user("ann@x.test")
    _in_training(u)  # a tuition-paying member in AY 2023
    # Two non-tier charges from the same payer in one AY → payment plan.
    plans = _plan([
        _charge(cid="ch_a", pi="pi_a", amount=50000, description=""),   # $500
        _charge(cid="ch_b", pi="pi_b", amount=50000, description=""),   # $500
    ])
    assert {p.action for p in plans} == {"create"}
    assert all(p.payment_type == "tuition" for p in plans)
    assert all("installment" in p.reason for p in plans)


def test_multiple_charges_from_known_non_student_not_tuition():
    u = _user("ann@x.test")
    _tenure(u, Profile.Role.ANALYST)  # known non-student that year → blocked
    plans = _plan([
        _charge(cid="ch_a", pi="pi_a", amount=50000, description=""),
        _charge(cid="ch_b", pi="pi_b", amount=50000, description=""),
    ])
    assert {p.action for p in plans} == {"needs_type"}


def test_multiple_charges_unknown_role_grouped_as_tuition():
    _user("ann@x.test")  # no tenure on record → benefit of the doubt
    plans = _plan([
        _charge(cid="ch_a", pi="pi_a", amount=50000, description=""),
        _charge(cid="ch_b", pi="pi_b", amount=50000, description=""),
    ])
    assert all(p.payment_type == "tuition" for p in plans)


def test_dues_links_to_period():
    from datetime import date

    from payments.models import DuesPeriod
    dp = DuesPeriod.objects.create(
        name="AY 2023–2024", slug="ay-2023-2024",
        start_date=date(2023, 9, 1), end_date=date(2024, 8, 31),
        due_date=date(2023, 12, 1),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"), dues_amount_analyst=Decimal("150"),
    )
    _user("ann@x.test")
    plans = _plan([_charge(amount=15000, description="")])  # $150, AY 2023
    assert plans[0].payment_type == "dues"
    assert plans[0].dues_period_id == dp.pk
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.dues_period_id == dp.pk


def test_amount_infers_tuition_static_fallback():
    _user("ann@x.test")  # no TuitionPeriod, but $2000 is a standard amount
    plans = _plan([_charge(amount=200000, description="")])
    assert plans[0].payment_type == "tuition"


def test_single_nontier_charge_stays_unknown():
    u = _user("ann@x.test")
    _in_training(u)
    plans = _plan([_charge(amount=50000, description="")])  # lone $500
    assert plans[0].action == "needs_type"


# ---- sweep-unknown (provisional) ------------------------------------------

def test_sweep_off_by_default():
    _user("ann@x.test")
    plans = _plan([_charge(amount=20000, description="")])  # $200 unknown
    assert plans[0].action == "needs_type"


def test_sweep_unknown_defaults_to_tuition():
    _user("ann@x.test")  # not analyst/scholar, <4 tuition years → still a student
    plans = _plan([_charge(amount=20000, description="")], sweep_unknown=True)
    assert plans[0].action == "create"
    assert plans[0].payment_type == "tuition"
    assert plans[0].provisional
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.source == Source.ASSUMED
    assert "provisional" in p.notes


def test_sweep_completed_member_is_registration():
    u = _user("ann@x.test")
    u.profile.role = Profile.Role.ANALYST  # completed tuition
    u.profile.save()
    plans = _plan([_charge(amount=20000, description="")], sweep_unknown=True)
    assert plans[0].payment_type == "registration"
    assert plans[0].provisional


def test_sweep_skips_tiny_charges():
    _user("ann@x.test")
    plans = _plan([_charge(amount=1000, description="")], sweep_unknown=True)  # $10
    assert plans[0].action == "needs_type"


# ---- only-types filter ----------------------------------------------------

def test_only_types_holds_back_other_types():
    _user("ann@x.test")
    rows = [normalize_charge(_charge(amount=15000, description=""))]  # $150 dues
    ctx = Command().build_context(None, only_types={"tuition"})
    plans = plan_charges(rows, ctx)
    assert plans[0].action == "skip_filtered"
    apply_plan(plans)
    assert not Payment.objects.filter(stripe_payment_intent_id="pi_1").exists()


def test_skip_failed_charge():
    _user("ann@x.test")
    plans = _plan([_charge(status="failed", paid=False)])
    assert plans[0].action == "skip_not_paid"


# ---- reconcile bucket -----------------------------------------------------

def test_reconcile_succeeded_site_payment():
    u = _user("ann@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_1", source=Source.STAFF,
    )
    plans = _plan([_charge()])
    assert plans[0].action == "reconcile"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.source == Source.VERIFIED  # confirmed by Stripe
    assert tag_for("ch_1") in p.notes


def test_reconcile_flag_pending_site_payment():
    u = _user("ann@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.PENDING, method=Payment.Method.STRIPE,
        stripe_payment_intent_id="pi_1", source=Source.STAFF,
    )
    plans = _plan([_charge()])
    assert plans[0].action == "reconcile_flag"
    apply_plan(plans)
    p = Payment.objects.get(stripe_payment_intent_id="pi_1")
    assert p.status == Payment.Status.PENDING  # not silently flipped
    assert tag_for("ch_1") in p.notes


def test_reconcile_by_session_metadata():
    u = _user("ann@x.test")
    existing = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.STAFF,
    )
    sessions = {"pi_1": {"id": "cs_1", "payment_intent": "pi_1",
                         "metadata": {"payment_id": str(existing.pk)}}}
    plans = _plan([_charge()], sessions=sessions)
    assert plans[0].action == "reconcile"
    assert plans[0].existing_payment_id == existing.pk


# ---- overlap & idempotency ------------------------------------------------

def _offline_ledger_row(user):
    return Payment.objects.create(
        payment_type=Payment.Type.DUES, user=user, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, paid_at=DAY,
    )


def test_overlap_with_ledger_skipped_then_allowed():
    u = _user("ann@x.test")
    _offline_ledger_row(u)
    plans = _plan([_charge(description="dues")])
    assert plans[0].action == "overlap"
    apply_plan(plans)
    assert not Payment.objects.filter(stripe_payment_intent_id="pi_1").exists()
    # Forcing it creates the row anyway.
    plans = _plan([_charge(description="dues")], allow_overlaps=True)
    assert plans[0].action == "create"


def test_dues_overlap_by_member_and_ay():
    u = _user("ann@x.test")
    # Member already has a succeeded dues row for AY 2023 (ledger, $150).
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, paid_at=DAY,
    )
    # A Stripe dues charge for the same AY — even a different tier — is a dup.
    plans = _plan([_charge(amount=10000, description="dues")])  # $100, AY 2023
    assert plans[0].action == "overlap"
    assert "academic year" in plans[0].reason


def test_amount_only_dues_guess_is_dropped_not_swallowed():
    """A dues *guess* from the amount alone must not suppress a real charge.

    Task #474: two off-site charges ($50 and $100) went unrecorded because
    those amounts happen to match dues tiers, and each payer had already paid
    dues that year — so the guess made itself into its own duplicate proof. A
    second same-year payment is more likely a seminar fee than dues paid
    twice, so the weak guess is what gives way, and the charge surfaces as
    unknown for a human to classify.
    """
    u = _user("ann@x.test")
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        source=Source.IMPORTED, paid_at=DAY,
    )
    # $100 matches a dues tier, but nothing *says* dues — no description, no
    # session metadata.
    plans = _plan([_charge(amount=10000, description="")])

    assert plans[0].action == "needs_type"
    assert plans[0].user_id == u.id


def test_ledger_twin_of_a_stripe_dues_charge_is_still_a_duplicate():
    """The other half of #474: don't re-import money the ledger already has.

    The treasurer's spreadsheet import recorded ~60 of the 2024 dues-season
    Stripe payments as ``method=stripe, source=imported`` rows carrying **no
    payment_intent** — so they can't be matched by id, only by amount + date.
    They are the same money and must stay suppressed.
    """
    u = _user("ann@x.test")
    Payment.objects.create(              # the spreadsheet twin: same day, same amount
        payment_type=Payment.Type.DUES, user=u, amount=Decimal("100.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.STRIPE,
        source=Source.IMPORTED, paid_at=DAY,
    )
    plans = _plan([_charge(amount=10000, description="")])

    assert plans[0].action == "overlap"


def test_amount_only_dues_guess_still_imports_when_no_dues_that_year():
    """The amount guess is still good when it isn't contradicted."""
    _user("ann@x.test")
    plans = _plan([_charge(amount=10000, description="")])

    assert plans[0].action == "create"
    assert plans[0].payment_type == "dues"


def test_idempotent_rerun_skips():
    _user("ann@x.test")
    plans = _plan([_charge(description="dues")])
    apply_plan(plans)
    # Re-plan: the tag is now in the DB, so the charge is skipped.
    plans2 = _plan([_charge(description="dues")])
    assert plans2[0].action == "skip_already"
    apply_plan(plans2)
    assert Payment.objects.filter(stripe_payment_intent_id="pi_1").count() == 1


# ---- _fetch's session→payment_intent mapping (SDK-object tolerant) --------

class _FakeStripeObject:
    """Mimics a stripe-python v15 SDK object: attribute access for real fields,
    and — crucially — NO dict-style ``.get`` method. Accessing ``.get`` falls
    through to ``__getattr__``, which looks up a field named ``get``, finds none,
    and raises ``AttributeError`` — exactly what broke ``_fetch`` in prod."""

    def __init__(self, **data):
        self.__dict__["_data"] = data

    def __getattr__(self, key):
        try:
            return self.__dict__["_data"][key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def test_session_payment_intent_id_handles_sdk_object_and_expansion():
    from payments.management.commands.import_stripe_payments import (
        _session_payment_intent_id,
    )

    # Bare id string (unexpanded payment_intent) on a stripe SDK object.
    s = _FakeStripeObject(id="cs_1", payment_intent="pi_1")
    assert _session_payment_intent_id(s) == "pi_1"

    # Expanded payment_intent object → dig out its id.
    s2 = _FakeStripeObject(id="cs_2", payment_intent=_FakeStripeObject(id="pi_2"))
    assert _session_payment_intent_id(s2) == "pi_2"

    # Session with no payment_intent must yield "" (not raise).
    s3 = _FakeStripeObject(id="cs_3")
    assert _session_payment_intent_id(s3) == ""

    # Plain dicts (older SDK / test doubles) still work.
    assert _session_payment_intent_id({"payment_intent": "pi_3"}) == "pi_3"
    assert _session_payment_intent_id({}) == ""
