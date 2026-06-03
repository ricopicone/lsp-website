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
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from accounts.models import Source

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
    overlap_pk = _find_overlap(ctx, user_id, row)
    if overlap_pk is not None and not allow_overlaps:
        return ChargePlan(
            row, "overlap",
            "likely duplicate of an existing imported payment",
            user_id=user_id, member_match=confidence, overlap_payment_id=overlap_pk,
        )

    ptype = classify_type(row, ctx.valid_types)
    type_inferred = ptype is not None
    if ptype is None:
        ptype = ctx.default_type
    if ptype is None:
        return ChargePlan(
            row, "needs_type", "type not inferable (pass --default-type to sweep)",
            user_id=user_id, member_match=confidence,
        )

    action = "create" if user_id is not None else "create_unmatched"
    return ChargePlan(
        row, action,
        "new historical payment" if user_id is not None else "new payment, member unmatched",
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
    return [plan_charge(r, ctx, allow_overlaps=allow_overlaps) for r in rows]


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
