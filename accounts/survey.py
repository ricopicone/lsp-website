"""Member intake survey — prefill + reconciliation-aware application.

The survey captures a member's best-guess year grid (which years they paid
tuition — *in full* or *partially* — and dues), their formation-step years
(palimpsest / passage / traversée), and their advisor. Because the historical
data is *already imported*, applying it reconciles against existing records
rather than blindly creating rows:

* a year we already have a record for → the record is **confirmed**
  (``source`` → VERIFIED);
* a year we have nothing for → a **SELF_REPORTED** row is created (the fallback);
* an unmarked tuition year for a current student → **SKIPPING** (self-reported),
  unless a payment on record contradicts it (then the record is kept).

The formation years build a precise ``MembershipTenure`` chain (role at each AY).
Re-applying is idempotent.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .membership import current_academic_year_start as ay_of
from .models import MemberIntakeSurvey, MembershipTenure, Profile, Source, User

R = Profile.Role

#: Formation-step questions shown per current role (key, label).
MILESTONES_BY_ROLE: dict[str, list[tuple[str, str]]] = {
    R.CANDIDATE: [("palimpsest", "Palimpsest")],
    R.CANDIDATE_SCHOLAR: [("palimpsest", "Palimpsest")],
    R.ANALYST: [("palimpsest", "Palimpsest"), ("passage", "Passage")],
    R.SCHOLAR: [("palimpsest", "Palimpsest"), ("traversee", "Traversée")],
}

#: Role progression per track: (milestone key that starts the segment, role).
#: ``None`` key → the segment starts at year_joined.
_TRACK_CHAIN: dict[str, list[tuple[str | None, str]]] = {
    R.ANALYST: [(None, R.PRE_CANDIDATE), ("palimpsest", R.CANDIDATE), ("passage", R.ANALYST)],
    R.CANDIDATE: [(None, R.PRE_CANDIDATE), ("palimpsest", R.CANDIDATE)],
    R.SCHOLAR: [
        (None, R.PRE_CANDIDATE_SCHOLAR), ("palimpsest", R.CANDIDATE_SCHOLAR),
        ("traversee", R.SCHOLAR),
    ],
    R.CANDIDATE_SCHOLAR: [(None, R.PRE_CANDIDATE_SCHOLAR), ("palimpsest", R.CANDIDATE_SCHOLAR)],
}


# ---------------------------------------------------------------------------
# Prefill
# ---------------------------------------------------------------------------

def survey_year_rows(user) -> list[dict]:
    """Grid rows, current AY back to the earliest period, pre-filled from records
    so members *correct* rather than recall. Tuition is three-state
    (full / partial / none) computed from the recorded amount."""
    from payments.models import DuesPeriod, TuitionEnrollment, TuitionPeriod

    tuition_by_ay = {ay_of(tp.start_date): tp for tp in TuitionPeriod.objects.all()}
    dues_by_ay = {ay_of(dp.start_date): dp for dp in DuesPeriod.objects.all()}
    years = sorted(set(tuition_by_ay) | set(dues_by_ay), reverse=True)

    tuition_paid_by_ay = _tuition_paid_by_ay(user)
    dues_ays = _paid_dues_ays(user)
    enroll_by_period = {
        e.tuition_period_id: e for e in TuitionEnrollment.objects.filter(user=user)
    }
    cur = ay_of(timezone.localdate())
    rows = []
    for ay in years:
        tp = tuition_by_ay.get(ay)
        dp = dues_by_ay.get(ay)
        state, paid = "", Decimal("0")
        if tp is not None:
            state, paid = _tuition_state(
                enroll_by_period.get(tp.id), tuition_paid_by_ay.get(ay, Decimal("0")),
                tp.tuition_amount or Decimal("0"),
            )
        rows.append({
            "ay": ay,
            "label": f"AY {ay}–{ay + 1}" + (" (current)" if ay == cur else ""),
            "has_tuition": tp is not None,
            "has_dues": dp is not None,
            "tuition_state": state,
            "tuition_paid": paid,
            "tuition_full": tp.tuition_amount if tp else None,
            "dues_checked": ay in dues_ays,
        })
    return rows


def _tuition_state(enrollment, paid, full):
    """(state, paid) where state is 'full' / 'partial' / ''."""
    if enrollment is not None:
        if enrollment.status == "paid_in_full":
            return "full", paid
        if enrollment.status in ("payment_plan", "committed"):
            return "partial", paid
        if enrollment.status == "skipping":
            return "", paid
    if paid <= 0:
        return "", paid
    return ("full" if full and paid >= full else "partial"), paid


def milestone_questions(user) -> list[dict]:
    """The formation-step questions to show for this member's current role,
    pre-filled from a prior submission."""
    survey = MemberIntakeSurvey.objects.filter(user=user).first()
    saved = (survey.milestones if survey else {}) or {}
    return [
        {"key": key, "label": label, "value": saved.get(key) or ""}
        for key, label in MILESTONES_BY_ROLE.get(user.profile.role, [])
    ]


def _tuition_paid_by_ay(user) -> dict[int, Decimal]:
    from payments.models import Payment
    out: dict[int, Decimal] = {}
    for paid_at, amount in Payment.objects.filter(
        payment_type=Payment.Type.TUITION, status=Payment.Status.SUCCEEDED,
        user=user, paid_at__isnull=False,
    ).values_list("paid_at", "amount"):
        ay = ay_of(paid_at.date())
        out[ay] = out.get(ay, Decimal("0")) + amount
    return out


def _paid_dues_ays(user) -> set[int]:
    from payments.models import Payment
    return {
        ay_of(paid_at.date())
        for paid_at, in Payment.objects.filter(
            payment_type=Payment.Type.DUES, status=Payment.Status.SUCCEEDED,
            user=user, paid_at__isnull=False,
        ).values_list("paid_at")
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_grid(post) -> dict:
    """``tuition_<ay>`` (radio: full/partial) + ``dues_<ay>`` (checkbox) → grid
    shape ``{"2024": {"tuition": "full", "dues": true}, ...}``."""
    grid: dict = {}
    for key in post:
        if key.startswith("tuition_"):
            val = post.get(key)
            if val in ("full", "partial"):
                grid.setdefault(key[len("tuition_"):], {})["tuition"] = val
        elif key.startswith("dues_"):
            grid.setdefault(key[len("dues_"):], {})["dues"] = True
    return grid


def parse_milestones(post) -> dict:
    """``milestone_<key>`` year inputs → ``{"palimpsest": 2019, ...}``."""
    out: dict = {}
    for key in post:
        if key.startswith("milestone_"):
            raw = (post.get(key) or "").strip()
            if raw.isdigit():
                out[key[len("milestone_"):]] = int(raw)
    return out


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

@transaction.atomic
def apply_survey(
    user, *, year_joined, pronouns, payment_names, payment_emails, grid,
    milestones=None, list_in_directory=None,
) -> MemberIntakeSurvey:
    """Store the raw survey and reconcile it into structured records."""
    milestones = milestones or {}
    survey, _ = MemberIntakeSurvey.objects.get_or_create(user=user)
    survey.year_joined = year_joined
    survey.payment_names = (payment_names or "").strip()[:255]
    survey.payment_emails = (payment_emails or "").strip()[:255]
    survey.grid = grid
    survey.milestones = milestones
    survey.submitted_at = timezone.now()
    survey.save()

    profile = user.profile
    updates = []
    if year_joined and profile.year_joined != year_joined:
        profile.year_joined = year_joined
        updates.append("year_joined")
    if pronouns is not None and profile.pronouns != pronouns:
        profile.pronouns = pronouns
        updates.append("pronouns")
    if list_in_directory is not None and profile.public != list_in_directory:
        profile.public = list_in_directory
        updates.append("public")
    if updates:
        profile.save(update_fields=updates)

    _seed_tenure_chain(user, profile, year_joined, milestones)
    _reconcile_grid(user, profile, grid, year_joined)

    survey.applied_at = timezone.now()
    survey.save(update_fields=["applied_at"])
    return survey


def _seed_tenure_chain(user, profile, year_joined, milestones) -> None:
    """Build the member's role timeline from join-year + formation milestones.
    Skips entirely if authoritative (non-self-reported) tenures exist; otherwise
    rebuilds the self-reported chain idempotently."""
    if MembershipTenure.objects.filter(user=user).exclude(
        source=Source.SELF_REPORTED
    ).exists():
        return

    chain = _TRACK_CHAIN.get(profile.role)
    segments: list[tuple[int, str]] = []
    if chain:
        for key, role in chain:
            start = year_joined if key is None else milestones.get(key)
            if start:
                segments.append((int(start), role))
    elif year_joined:
        segments.append((int(year_joined), profile.role))

    segments.sort()
    clean: list[tuple[int, str]] = []
    for start, role in segments:
        if not clean or start > clean[-1][0]:  # strictly increasing only
            clean.append((start, role))
    if not clean:
        return

    MembershipTenure.objects.filter(user=user, source=Source.SELF_REPORTED).delete()
    for i, (start, role) in enumerate(clean):
        end = clean[i + 1][0] - 1 if i + 1 < len(clean) else None
        MembershipTenure.objects.create(
            user=user, role=role, start_ay=start, end_ay=end,
            source=Source.SELF_REPORTED, notes="From intake survey.",
        )


def _reconcile_grid(user, profile, grid, year_joined) -> None:
    from payments.models import DuesPeriod, TuitionPeriod

    tuition_by_ay = {ay_of(tp.start_date): tp for tp in TuitionPeriod.objects.all()}
    dues_by_ay = {ay_of(dp.start_date): dp for dp in DuesPeriod.objects.all()}
    current_in_training = profile.role in Profile.IN_TRAINING_ROLES

    for ay_str, ans in (grid or {}).items():
        try:
            ay = int(ay_str)
        except (TypeError, ValueError):
            continue
        tp = tuition_by_ay.get(ay)
        if tp is not None:
            _reconcile_tuition(
                user, tp, ay, ans.get("tuition", ""), current_in_training, year_joined,
            )
        dp = dues_by_ay.get(ay)
        if dp is not None and ans.get("dues"):
            _reconcile_dues(user, dp, profile)


def _reconcile_tuition(user, tp, ay, state, current_in_training, year_joined):
    from payments.models import Payment, TuitionEnrollment

    has_payment = Payment.objects.filter(
        payment_type=Payment.Type.TUITION, status=Payment.Status.SUCCEEDED,
        user=user, paid_at__date__gte=tp.start_date, paid_at__date__lte=tp.end_date,
    ).exists()
    enrollment = TuitionEnrollment.objects.filter(user=user, tuition_period=tp).first()
    S = TuitionEnrollment.Status

    if state in ("full", "partial"):
        target = S.PAID_IN_FULL if state == "full" else S.PAYMENT_PLAN
        source = Source.VERIFIED if has_payment else Source.SELF_REPORTED
        if enrollment is None:
            TuitionEnrollment.objects.create(
                user=user, tuition_period=tp, status=target, source=source,
                notes="From intake survey.",
            )
        elif enrollment.status == S.SKIPPING or enrollment.source in (
            Source.ASSUMED, Source.SELF_REPORTED
        ):
            enrollment.status = target
            enrollment.source = source
            enrollment.save(update_fields=["status", "source"])
        elif has_payment and enrollment.source != Source.VERIFIED:
            enrollment.source = Source.VERIFIED  # member confirmed an on-record year
            enrollment.save(update_fields=["source"])
        return

    # Unmarked → none / skipped.
    if has_payment:
        return  # record says paid — keep it; the member's claim is in the raw grid
    if current_in_training and (not year_joined or ay >= year_joined):
        if enrollment is None:
            TuitionEnrollment.objects.create(
                user=user, tuition_period=tp, status=S.SKIPPING,
                source=Source.SELF_REPORTED, notes="Skipped (intake survey).",
            )
        elif enrollment.source in (Source.ASSUMED, Source.SELF_REPORTED) \
                and enrollment.status != S.PAID_IN_FULL:
            enrollment.status = S.SKIPPING
            enrollment.source = Source.SELF_REPORTED
            enrollment.save(update_fields=["status", "source"])


def _reconcile_dues(user, dp, profile):
    from payments.models import Payment

    existing = Payment.objects.filter(
        payment_type=Payment.Type.DUES, status=Payment.Status.SUCCEEDED,
        user=user, dues_period=dp,
    ).first()
    if existing is not None:
        if existing.source != Source.VERIFIED:
            existing.source = Source.VERIFIED
            existing.save(update_fields=["source"])
        return
    amount = dp.amount_for_role(profile.role) or dp.dues_amount_analyst or Decimal("0")
    Payment.objects.create(
        payment_type=Payment.Type.DUES, user=user, amount=amount, currency="usd",
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        dues_period=dp, source=Source.SELF_REPORTED,
        paid_at=timezone.make_aware(
            timezone.datetime(dp.start_date.year, dp.start_date.month, dp.start_date.day, 12)
        ),
        notes="Member-reported via intake survey (estimated amount).",
    )


__all__ = [
    "apply_survey", "survey_year_rows", "milestone_questions",
    "parse_grid", "parse_milestones", "User",
]
