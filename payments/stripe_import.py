"""Historical Stripe import — planning logic (no network, no Stripe SDK here).

This module turns a list of **already-fetched** Stripe charges into a plan of
DB actions, and applies that plan. Keeping it SDK-free makes it unit-testable
with synthetic charge dicts; the management command
(``import_stripe_payments``) does the live fetch and hands the rows here.

Two buckets, decided per charge:

* **reconcile** — the charge corresponds to a ``Payment`` this site already
  created at checkout (matched by payment-intent id, checkout-session id, or the
  session's ``metadata.payment_id``). We attach the Stripe ids, tag it, and
  (for an already-succeeded row) upgrade its provenance to *verified*. A site
  row still marked pending/failed is **flagged, not silently flipped** — staff
  complete it via the admin so the registration side-effects fire.
* **create** — no existing row (a charge taken outside this site: Wix-era,
  Payment Links, invoices). We create a ``Payment`` (``method=stripe``,
  ``source=imported``, ``status=succeeded``), matching the member by email then
  by name (high-confidence only). Before creating we check for a likely
  **overlap** with a payment already imported from the treasurer ledger (same
  member + amount within a few days) and, by default, skip it for staff review
  rather than double-count.

Everything is idempotent: each touched row carries a ``[stripe-import:<id>]``
tag in its notes, and a re-run skips charges whose tag is already present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from accounts.membership import current_academic_year_start
from accounts.models import Source

#: Fallback dues amounts when no DuesPeriod covers a charge's year — the three
#: standard tiers (pre-candidate / candidate / analyst·scholar). Most charges at
#: these amounts are dues (historical years may have no DuesPeriod row).
DEFAULT_DUES_AMOUNTS = frozenset({Decimal("50"), Decimal("100"), Decimal("150")})

#: Standard full-year tuition amounts across the years we have ($2500 current,
#: $2000 earlier) — used when no TuitionPeriod row covers the charge's year.
DEFAULT_TUITION_AMOUNTS = frozenset({Decimal("2000"), Decimal("2500")})

#: Marker written into Payment.notes; also the idempotency key on re-runs.
TAG_RE = re.compile(r"\[stripe-import:([^\]]+)\]")


def tag_for(charge_id: str) -> str:
    return f"[stripe-import:{charge_id}]"


# ---------------------------------------------------------------------------
# Normalising a Stripe charge (works on SDK objects or plain dicts)
# ---------------------------------------------------------------------------

def _g(obj, *keys, default=None):
    """Read ``obj[key]`` / ``obj.key`` following a dotted path, tolerant of both
    Stripe SDK objects (attribute + item access) and plain dicts."""
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return default if cur is None else cur


@dataclass
class StripeChargeRow:
    charge_id: str
    amount: Decimal                 # dollars
    currency: str
    created: datetime               # aware UTC
    status: str                     # succeeded | pending | failed
    paid: bool
    refunded: bool                  # fully refunded
    amount_refunded: Decimal
    email: str
    name: str
    payment_intent: str
    checkout_session_id: str
    session_payment_id: str         # session.metadata.payment_id, if any
    session_payment_type: str       # session.metadata.payment_type, if any
    description: str


def normalize_charge(charge, *, sessions_by_pi: dict | None = None) -> StripeChargeRow:
    """Build a :class:`StripeChargeRow` from a Stripe charge plus an optional
    ``payment_intent_id -> checkout.Session`` map (for site-checkout linking)."""
    sessions_by_pi = sessions_by_pi or {}
    cents = _g(charge, "amount", default=0) or 0
    refunded_cents = _g(charge, "amount_refunded", default=0) or 0
    created_ts = _g(charge, "created", default=0) or 0
    pi = _g(charge, "payment_intent", default="") or ""
    if isinstance(pi, dict):  # expanded payment_intent object
        pi = _g(pi, "id", default="") or ""
    email = (
        _g(charge, "billing_details", "email")
        or _g(charge, "receipt_email")
        or _g(charge, "customer", "email")
        or ""
    )
    name = _g(charge, "billing_details", "name") or _g(charge, "customer", "name") or ""

    session = sessions_by_pi.get(pi) if pi else None
    return StripeChargeRow(
        charge_id=_g(charge, "id", default="") or "",
        amount=(Decimal(cents) / 100).quantize(Decimal("0.01")),
        currency=(_g(charge, "currency", default="usd") or "usd").lower(),
        created=datetime.fromtimestamp(int(created_ts), tz=dt_timezone.utc),
        status=_g(charge, "status", default="") or "",
        paid=bool(_g(charge, "paid", default=False)),
        refunded=bool(_g(charge, "refunded", default=False)),
        amount_refunded=(Decimal(refunded_cents) / 100).quantize(Decimal("0.01")),
        email=(email or "").strip(),
        name=(name or "").strip(),
        payment_intent=pi,
        checkout_session_id=_g(session, "id", default="") or "",
        session_payment_id=str(_g(session, "metadata", "payment_id", default="") or ""),
        session_payment_type=str(_g(session, "metadata", "payment_type", default="") or ""),
        description=(_g(charge, "description", default="") or "").strip(),
    )


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS = [
    ("tuition", "tuition"),
    ("dues", "dues"),
    ("donation", "donation"),
    ("donate", "donation"),
    ("gift", "donation"),
    ("registration", "registration"),
    ("register", "registration"),
    ("seminar", "registration"),
    ("workshop", "registration"),
]


def classify_type(row: StripeChargeRow, valid_types: set[str]) -> str | None:
    """Infer the payment type from the checkout-session metadata, then from the
    charge description. Returns a Payment.Type value or None when unknown."""
    if row.session_payment_type in valid_types:
        return row.session_payment_type
    text = row.description.lower()
    for keyword, ptype in _TYPE_KEYWORDS:
        if keyword in text and ptype in valid_types:
            return ptype
    return None


def ay_of(d) -> int:
    """Academic-year start year for a charge date (AY runs Sep 1 – Aug 31)."""
    return current_academic_year_start(d)


def infer_type(row: StripeChargeRow, ctx) -> tuple[str | None, str]:
    """Best-effort payment type, returning ``(type, how)``. Tries, in order:
    checkout-session metadata, description keywords, then a **data-driven amount
    match** — the charge's amount against that academic year's dues tiers (from
    DuesPeriod, plus the standard fallback tiers) and the year's tuition amount.
    ``how`` is "metadata" / "description" / "amount" / "" (unknown). Tuition
    *installments* aren't matched here (amounts vary) — see the multi-charge
    grouping pass in :func:`plan_charges`."""
    kw = classify_type(row, ctx.valid_types)
    if kw is not None:
        how = "metadata" if row.session_payment_type in ctx.valid_types else "description"
        return kw, how
    ay = ay_of(row.created.date())
    dues_amts = ctx.dues_amounts_by_ay.get(ay, frozenset()) | ctx.static_dues
    if row.amount in dues_amts and "dues" in ctx.valid_types:
        return "dues", "amount"
    period_tuition = ctx.tuition_by_ay.get(ay)
    tuition_amts = ctx.static_tuition | (
        {period_tuition} if period_tuition is not None else set()
    )
    if row.amount in tuition_amts and "tuition" in ctx.valid_types:
        return "tuition", "amount"
    return None, ""


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

ACTIONS = (
    "skip_not_paid",       # failed / unpaid charge — no money, ignored
    "skip_already",        # tag already present — idempotent re-run
    "reconcile",           # matched a succeeded site Payment; ids + verified
    "reconcile_flag",      # matched a site Payment still pending/failed — review
    "create",              # new historical Payment created
    "create_unmatched",    # created, but no member matched (user left null)
    "needs_type",          # no existing row and type couldn't be inferred
    "overlap",             # likely duplicate of a treasurer-ledger import
    "skip_filtered",       # type held back by --only-types
)


@dataclass
class ChargePlan:
    row: StripeChargeRow
    action: str
    reason: str
    payment_type: str | None = None
    user_id: int | None = None
    member_match: str = ""           # confidence label from the matcher
    type_inferred: bool = False
    existing_payment_id: int | None = None
    overlap_payment_id: int | None = None


@dataclass
class PlanContext:
    """Everything plan_charges needs, built once from the DB by the caller."""
    valid_types: set[str]
    tags_seen: set[str]                          # charge ids already imported
    payment_by_pi: dict                          # pi -> Payment
    payment_by_session: dict                     # session id -> Payment
    payment_by_pk: dict                          # pk -> Payment (metadata.payment_id)
    email_to_user: dict                          # email lower -> user_id
    matcher: object                              # NameMatcher
    overlaps_by_user: dict                       # user_id -> [(amount, date, pk)]
    dues_amounts_by_ay: dict = field(default_factory=dict)   # ay -> {tier amounts}
    tuition_by_ay: dict = field(default_factory=dict)        # ay -> tuition amount
    static_dues: frozenset = DEFAULT_DUES_AMOUNTS
    static_tuition: frozenset = DEFAULT_TUITION_AMOUNTS
    #: {(user_id, ay): payment_pk} where a succeeded dues payment already exists.
    #: Dues are once-per-member-per-year, so a charge for an (member, AY) already
    #: on record is a duplicate (catches ledger dues the ±7-day check would miss).
    existing_dues_ay: dict = field(default_factory=dict)
    #: {(user_id, ay)} the member held a *non*-student role — installment
    #: inference is blocked for these (their several charges aren't a payment
    #: plan). A member with no role on record that year is given the benefit of
    #: the doubt (historical years often lack tenure data).
    non_student_user_ays: set | None = None
    only_types: set | None = None                # restrict which types to create
    default_type: str | None = None
    overlap_days: int = 7


def _find_overlap(plan_ctx: PlanContext, user_id, row) -> int | None:
    if user_id is None:
        return None
    charge_date = row.created.date()
    for amount, paid_date, pk in plan_ctx.overlaps_by_user.get(user_id, ()):
        if amount == row.amount and abs((paid_date - charge_date).days) <= plan_ctx.overlap_days:
            return pk
    return None


def plan_charge(row: StripeChargeRow, ctx: PlanContext, *, allow_overlaps=False) -> ChargePlan:
    """Decide what to do with a single normalized charge."""
    # Idempotency first.
    if row.charge_id in ctx.tags_seen:
        return ChargePlan(row, "skip_already", "already imported (tag present)")

    # Only real money: succeeded (incl. later refunded) charges.
    if not (row.paid and row.status == "succeeded"):
        return ChargePlan(row, "skip_not_paid", f"charge status={row.status} paid={row.paid}")

    # --- Reconcile against an existing site Payment? ---
    existing = None
    if row.payment_intent:
        existing = ctx.payment_by_pi.get(row.payment_intent)
    if existing is None and row.checkout_session_id:
        existing = ctx.payment_by_session.get(row.checkout_session_id)
    if existing is None and row.session_payment_id:
        existing = ctx.payment_by_pk.get(_as_int(row.session_payment_id))
    if existing is not None:
        succeeded = existing.status == "succeeded"
        return ChargePlan(
            row,
            "reconcile" if succeeded else "reconcile_flag",
            "site payment matched"
            if succeeded
            else f"site payment is '{existing.status}'; complete it via admin",
            existing_payment_id=existing.pk,
        )

    # --- Create a new historical row. ---
    user_id, confidence = _match_member(row, ctx)
    ptype, how = infer_type(row, ctx)
    type_inferred = ptype is not None
    ay = ay_of(row.created.date())

    # Duplicate guard (type-aware). Dues are once-per-member-per-year, so an
    # (member, AY) already on record is a duplicate — stronger than a date
    # window. Other types fall back to the amount + ±N-day match.
    overlap_pk = None
    reason = "likely duplicate of an existing imported payment"
    if ptype == "dues" and user_id is not None:
        overlap_pk = ctx.existing_dues_ay.get((user_id, ay))
        if overlap_pk is not None:
            reason = "member already has dues recorded for this academic year"
    if overlap_pk is None:
        overlap_pk = _find_overlap(ctx, user_id, row)
    if overlap_pk is not None and not allow_overlaps:
        return ChargePlan(
            row, "overlap", reason,
            user_id=user_id, member_match=confidence, overlap_payment_id=overlap_pk,
        )

    if ptype is None:
        ptype = ctx.default_type
    if ptype is None:
        return ChargePlan(
            row, "needs_type", "type not inferable (pass --default-type to sweep)",
            user_id=user_id, member_match=confidence,
        )

    action = "create" if user_id is not None else "create_unmatched"
    reason = (
        f"new historical payment ({how} type)" if user_id is not None
        else f"new payment, member unmatched ({how} type)"
    )
    return ChargePlan(
        row, action, reason,
        payment_type=ptype, user_id=user_id, member_match=confidence,
        type_inferred=type_inferred, overlap_payment_id=overlap_pk,
    )


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_member(row: StripeChargeRow, ctx: PlanContext):
    """Return (user_id, confidence). Email exact-match first, then the
    high-confidence name matcher."""
    if row.email:
        uid = ctx.email_to_user.get(row.email.lower())
        if uid is not None:
            return uid, "email"
    if row.name:
        result = ctx.matcher.match(row.name)
        if result.user_id is not None:
            return result.user_id, result.confidence
    return None, "none"


def plan_charges(rows, ctx: PlanContext, *, allow_overlaps=False) -> list[ChargePlan]:
    plans = [plan_charge(r, ctx, allow_overlaps=allow_overlaps) for r in rows]
    _infer_installments(plans, ctx)
    _apply_type_filter(plans, ctx)
    return plans


def _infer_installments(plans: list[ChargePlan], ctx: PlanContext) -> None:
    """Payment-plan rule: when a matched payer has two or more charges in one
    academic year whose type couldn't otherwise be inferred, treat them as
    tuition installments (a single such charge stays ``needs_type`` — it might
    be a one-off donation)."""
    if "tuition" not in ctx.valid_types:
        return
    groups: dict = {}
    for p in plans:
        if p.action == "needs_type" and p.user_id is not None:
            groups.setdefault((p.user_id, ay_of(p.row.created.date())), []).append(p)
    for (uid, ay), members in groups.items():
        if len(members) < 2:
            continue
        # Skip only when we positively know this member wasn't a student that
        # year (e.g. an analyst's repeat donations). Unknown role → allow.
        if ctx.non_student_user_ays is not None and (uid, ay) in ctx.non_student_user_ays:
            continue
        for p in members:
            p.action = "create"
            p.payment_type = "tuition"
            p.type_inferred = True
            p.reason = "tuition installment (multiple charges in one AY)"


def _apply_type_filter(plans: list[ChargePlan], ctx: PlanContext) -> None:
    """Hold back create rows whose type isn't in ``--only-types`` (reconciles are
    always safe and unaffected)."""
    if not ctx.only_types:
        return
    for p in plans:
        if p.action in ("create", "create_unmatched") and p.payment_type not in ctx.only_types:
            p.action = "skip_filtered"
            p.reason = f"held back — {p.payment_type} not in --only-types"


# ---------------------------------------------------------------------------
# Applying a plan
# ---------------------------------------------------------------------------

def apply_plan(plans: list[ChargePlan]) -> dict:
    """Execute the create/reconcile actions. Caller wraps this in a transaction
    and only calls it on ``--commit``. Returns a counts dict."""
    from .models import Payment

    counts = {a: 0 for a in ACTIONS}
    for plan in plans:
        row = plan.row
        if plan.action in ("create", "create_unmatched"):
            status = Payment.Status.REFUNDED if row.refunded else Payment.Status.SUCCEEDED
            Payment.objects.create(
                payment_type=plan.payment_type,
                user_id=plan.user_id,
                amount=row.amount,
                currency=row.currency,
                status=status,
                method=Payment.Method.STRIPE,
                stripe_payment_intent_id=row.payment_intent,
                stripe_checkout_session_id=row.checkout_session_id,
                email=row.email,
                source=Source.IMPORTED,
                paid_at=row.created,
                notes=_compose_note(row, plan),
            )
        elif plan.action in ("reconcile", "reconcile_flag"):
            payment = Payment.objects.select_for_update().get(pk=plan.existing_payment_id)
            fields = []
            if row.payment_intent and not payment.stripe_payment_intent_id:
                payment.stripe_payment_intent_id = row.payment_intent
                fields.append("stripe_payment_intent_id")
            if tag_for(row.charge_id) not in payment.notes:
                payment.notes = (payment.notes + "\n" + tag_for(row.charge_id)).strip()
                fields.append("notes")
            # An already-succeeded site payment now confirmed by Stripe → verified.
            if plan.action == "reconcile" and payment.source != Source.VERIFIED:
                payment.source = Source.VERIFIED
                fields.append("source")
            if fields:
                payment.save(update_fields=fields)
        counts[plan.action] += 1
    return counts


def _compose_note(row: StripeChargeRow, plan: ChargePlan) -> str:
    bits = [tag_for(row.charge_id)]
    if row.description:
        bits.append(row.description)
    if not plan.type_inferred:
        bits.append("(type defaulted — verify)")
    if plan.action == "create_unmatched":
        bits.append(f"(unmatched payer: {row.name or row.email or '?'})")
    if row.refunded:
        bits.append("(refunded in Stripe)")
    return " ".join(bits)
