"""Member intake survey — prefill + reconciliation-aware application.

The survey captures a member's best-guess year grid (which years they paid
tuition / dues). Because the historical data is *already imported*, applying the
survey reconciles against existing records rather than blindly creating rows:

* a checked year that we already have a record for → the record is **confirmed**
  (``source`` upgraded to VERIFIED);
* a checked year we have nothing for → a **SELF_REPORTED** row is created (the
  fallback);
* an unchecked tuition year for a current student → **SKIPPING** (self-reported),
  unless a payment on record contradicts it (then the record is kept).

Re-applying is idempotent (keyed on user + period).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .membership import current_academic_year_start as ay_of
from .models import MemberIntakeSurvey, MembershipTenure, Profile, Source, User


def survey_year_rows(user) -> list[dict]:
    """Grid rows for the survey, current AY back to the earliest period, each
    pre-checked from existing records so members *correct* rather than recall."""
    from payments.models import DuesPeriod, TuitionEnrollment, TuitionPeriod

    tuition_by_ay = {ay_of(tp.start_date): tp for tp in TuitionPeriod.objects.all()}
    dues_by_ay = {ay_of(dp.start_date): dp for dp in DuesPeriod.objects.all()}
    years = sorted(set(tuition_by_ay) | set(dues_by_ay), reverse=True)

    paid_tuition_ays = _paid_tuition_ays(user)
    paid_dues_ays = _paid_dues_ays(user)
    enrolled_paid = {
        e.tuition_period_id for e in TuitionEnrollment.objects.filter(
            user=user, status__in=(
                TuitionEnrollment.Status.PAID_IN_FULL,
                TuitionEnrollment.Status.PAYMENT_PLAN,
                TuitionEnrollment.Status.COMMITTED,
            ),
        )
    }
    cur = current_academic_year_start_safe()
    rows = []
    for ay in years:
        tp = tuition_by_ay.get(ay)
        dp = dues_by_ay.get(ay)
        rows.append({
            "ay": ay,
            "label": f"AY {ay}–{ay + 1}" + (" (current)" if ay == cur else ""),
            "has_tuition": tp is not None,
            "has_dues": dp is not None,
            "tuition_checked": ay in paid_tuition_ays or (tp and tp.id in enrolled_paid),
            "dues_checked": ay in paid_dues_ays,
        })
    return rows


def current_academic_year_start_safe() -> int:
    return ay_of(timezone.localdate())


def _paid_tuition_ays(user) -> set[int]:
    from payments.models import Payment
    out = set()
    for paid_at, in Payment.objects.filter(
        payment_type=Payment.Type.TUITION, status=Payment.Status.SUCCEEDED,
        user=user, paid_at__isnull=False,
    ).values_list("paid_at"):
        out.add(ay_of(paid_at.date()))
    return out


def _paid_dues_ays(user) -> set[int]:
    from payments.models import Payment
    out = set()
    for paid_at, in Payment.objects.filter(
        payment_type=Payment.Type.DUES, status=Payment.Status.SUCCEEDED,
        user=user, paid_at__isnull=False,
    ).values_list("paid_at"):
        out.add(ay_of(paid_at.date()))
    return out


@transaction.atomic
def apply_survey(
    user, *, year_joined, pronouns, payment_names, payment_emails, grid,
) -> MemberIntakeSurvey:
    """Store the raw survey and reconcile its grid into structured records."""
    survey, _ = MemberIntakeSurvey.objects.get_or_create(user=user)
    survey.year_joined = year_joined
    survey.payment_names = (payment_names or "").strip()[:255]
    survey.payment_emails = (payment_emails or "").strip()[:255]
    survey.grid = grid
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
    if updates:
        profile.save(update_fields=updates)

    # Seed an approximate role timeline if the member has none on record.
    if year_joined and not MembershipTenure.objects.filter(user=user).exists():
        MembershipTenure.objects.create(
            user=user, role=profile.role, start_ay=year_joined,
            source=Source.SELF_REPORTED, notes="Seeded from intake survey.",
        )

    _reconcile_grid(user, profile, grid, year_joined)

    survey.applied_at = timezone.now()
    survey.save(update_fields=["applied_at"])
    return survey


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
                user, tp, ay, bool(ans.get("tuition")),
                current_in_training, year_joined,
            )
        dp = dues_by_ay.get(ay)
        if dp is not None and ans.get("dues"):
            _reconcile_dues(user, dp, profile)


def _reconcile_tuition(user, tp, ay, checked, current_in_training, year_joined):
    from payments.models import Payment, TuitionEnrollment

    has_payment = Payment.objects.filter(
        payment_type=Payment.Type.TUITION, status=Payment.Status.SUCCEEDED,
        user=user, paid_at__date__gte=tp.start_date, paid_at__date__lte=tp.end_date,
    ).exists()
    enrollment = TuitionEnrollment.objects.filter(
        user=user, tuition_period=tp
    ).first()
    S = TuitionEnrollment.Status

    if checked:
        target = S.PAID_IN_FULL
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

    # Unchecked.
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
            existing.source = Source.VERIFIED  # member confirmed
            existing.save(update_fields=["source"])
        return
    # No record — create a self-reported estimate at the role's tier.
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


def parse_grid(post) -> dict:
    """Pull ``tuition_<ay>`` / ``dues_<ay>`` checkboxes out of a POST into the
    stored grid shape ``{"2024": {"tuition": true, "dues": false}, ...}``."""
    grid: dict = {}
    for key in post:
        if key.startswith(("tuition_", "dues_")):
            kind, _, ay = key.partition("_")
            grid.setdefault(ay, {})[kind] = True
    return grid


# Re-export so callers can ``from accounts.survey import User`` if needed.
__all__ = ["apply_survey", "survey_year_rows", "parse_grid", "User"]
