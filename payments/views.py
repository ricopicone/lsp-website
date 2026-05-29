"""Public payment views: webhook, dues, donations, thanks, exports, dashboard."""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registrations.models import Registration

from .forms import DonationForm, TuitionDecisionForm
from .models import (
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)
from .operations import complete_payment
from .stripe_checkout import (
    create_donation_session,
    create_dues_session,
    create_tuition_session,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _is_staff(user):
    return user.is_authenticated and user.is_staff


TREASURER_TABS = [
    ("overview", "Overview"),
    ("tuition",  "Tuition"),
    ("dues",     "Dues"),
    ("settings", "Settings"),
]


def _treasurer_tab_links() -> list[tuple[str, str, str]]:
    """Returns [(key, label, url), ...] used by the tab nav."""
    from django.urls import reverse
    name_to_url = {
        "overview": reverse("treasurer"),
        "tuition":  reverse("treasurer_tuition"),
        "dues":     reverse("treasurer_dues"),
        "settings": reverse("treasurer_settings"),
    }
    return [(key, label, name_to_url[key]) for key, label in TREASURER_TABS]


def _treasurer_render(request, tab_key: str, template: str, ctx: dict):
    """Common render helper: injects the tab nav into every treasurer page."""
    ctx = {**ctx, "tab_key": tab_key, "tabs": _treasurer_tab_links()}
    return render(request, template, ctx)


@login_required
@user_passes_test(_is_staff)
def treasurer_dashboard(request):
    """Overview tab — compact highlights for both tuition and dues (M7.5)."""
    tuition_ctx = _treasurer_tuition_context()
    dues_ctx = _treasurer_dues_context()

    return _treasurer_render(request, "overview", "payments/treasurer/overview.html", {
        **dues_ctx,
        **tuition_ctx,
    })


@login_required
@user_passes_test(_is_staff)
def treasurer_tuition(request):
    """Tuition tab — full per-status table, per-role breakdown, reconciliation."""
    return _treasurer_render(
        request, "tuition", "payments/treasurer/tuition.html",
        _treasurer_tuition_context(),
    )


@login_required
@user_passes_test(_is_staff)
def treasurer_dues(request):
    """Dues tab — full per-period table, per-role breakdown, unpaid list, charts."""
    return _treasurer_render(
        request, "dues", "payments/treasurer/dues.html",
        _treasurer_dues_context(),
    )


def _treasurer_dues_context() -> dict:
    """Build the dues-section context — current period summary, multi-period
    totals, per-role breakdown, unpaid list, Chart.js payloads."""
    obligated_roles = list(settings.DUES_OBLIGATED_ROLES)
    obligated_count = User.objects.filter(
        is_active=True, profile__role__in=obligated_roles,
    ).count()

    periods = list(DuesPeriod.objects.order_by("-start_date"))
    period_stats = []
    for p in periods:
        paid_payments = p.payments.filter(status=Payment.Status.SUCCEEDED)
        paid_count = paid_payments.values("user").distinct().count()
        total = paid_payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        period_stats.append({
            "period": p,
            "paid_count": paid_count,
            "unpaid_count": max(obligated_count - paid_count, 0),
            "total_collected": total,
        })

    current = DuesPeriod.current()
    role_breakdown = []
    unpaid_users = []
    if current is not None:
        paid_user_ids = set(
            current.payments
            .filter(status=Payment.Status.SUCCEEDED)
            .values_list("user_id", flat=True)
        )
        for role in obligated_roles:
            users_in_role = User.objects.filter(
                is_active=True, profile__role=role,
            )
            total_in_role = users_in_role.count()
            paid_in_role = users_in_role.filter(id__in=paid_user_ids).count()
            role_breakdown.append({
                "role": role,
                "total": total_in_role,
                "paid": paid_in_role,
                "unpaid": total_in_role - paid_in_role,
            })
        unpaid_users = list(
            User.objects.filter(
                is_active=True, profile__role__in=obligated_roles,
            )
            .exclude(id__in=paid_user_ids)
            .select_related("profile")
            .order_by("last_name", "first_name", "email")
        )

    chart_periods = {
        "labels": [s["period"].name for s in reversed(period_stats)],
        "totals": [float(s["total_collected"]) for s in reversed(period_stats)],
    }
    chart_roles = {
        "labels": [r["role"] for r in role_breakdown],
        "paid": [r["paid"] for r in role_breakdown],
        "unpaid": [r["unpaid"] for r in role_breakdown],
    }
    return {
        "period_stats":   period_stats,
        "current_period": current,
        "role_breakdown": role_breakdown,
        "unpaid_users":   unpaid_users,
        "obligated_count": obligated_count,
        "chart_periods_json": json.dumps(chart_periods),
        "chart_roles_json": json.dumps(chart_roles),
    }


_INLINE_TUITION_STATUSES = {
    "committed":    "Committed",
    "skipping":     "Skipping",
    "exempt":       "Exempt",
}


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_tuition_set_status(request, user_id: int):
    """Set a user's tuition status for the current period (treasurer action).

    Used by the inline resolution buttons on the tuition reconciliation
    queue. ``status`` is one of: committed, skipping, exempt.
    """
    status = request.POST.get("status", "")
    if status not in _INLINE_TUITION_STATUSES:
        return redirect("treasurer_tuition")
    target = get_object_or_404(User, pk=user_id)
    period = TuitionPeriod.current()
    if period is None:
        return redirect("treasurer_tuition")
    with transaction.atomic():
        enr, _ = TuitionEnrollment.objects.update_or_create(
            user=target, tuition_period=period,
            defaults={"status": status},
        )
        enr.notes = (
            (enr.notes + "\n" if enr.notes else "")
            + f"[{timezone.now().date()}] Treasurer ({request.user.email}) "
            f"set status to {_INLINE_TUITION_STATUSES[status]}."
        )
        enr.save(update_fields=("notes",))
    return redirect("treasurer_tuition")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_tuition_record_offline_payment(request, user_id: int):
    """Record an offline tuition payment for the full annual amount.

    Creates (or reuses) a COMMITTED enrollment for the current period,
    mints a single full-amount TuitionInstallment, creates an OFFLINE
    Payment, and runs the standard ``complete_payment`` side-effects —
    which marks the installment paid and flips the enrollment to
    PAID_IN_FULL. The Payment.notes carries a short audit trail.
    """
    target = get_object_or_404(User, pk=user_id)
    period = TuitionPeriod.current()
    if period is None:
        return redirect("treasurer_tuition")
    with transaction.atomic():
        enr, _ = TuitionEnrollment.objects.update_or_create(
            user=target, tuition_period=period,
            defaults={"status": TuitionEnrollment.Status.COMMITTED},
        )
        installment = TuitionInstallment.objects.create(
            enrollment=enr, sequence=enr.installments.count() + 1,
            due_date=period.decision_due_date,
            amount=period.tuition_amount,
        )
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=target,
            amount=period.tuition_amount,
            method=Payment.Method.OFFLINE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
            notes=(
                f"Offline tuition payment recorded by treasurer "
                f"{request.user.email} on {timezone.now().date()}."
            ),
        )
    complete_payment(payment)
    return redirect("treasurer_tuition")


@login_required
@user_passes_test(_is_staff)
def treasurer_settings(request):
    """Settings tab — edit dues + tuition amounts for every academic year.

    Two formsets: one for every DuesPeriod row, one for every
    TuitionPeriod row. Single submit saves all changes atomically.
    """
    from django.forms import modelformset_factory

    from .forms import DuesPeriodRowForm, TuitionPeriodRowForm
    dues_qs = DuesPeriod.objects.order_by("-start_date")
    tuition_qs = TuitionPeriod.objects.order_by("-start_date")

    DuesFormSet = modelformset_factory(
        DuesPeriod, form=DuesPeriodRowForm, extra=0,
    )
    TuitionFormSet = modelformset_factory(
        TuitionPeriod, form=TuitionPeriodRowForm, extra=0,
    )

    if request.method == "POST":
        dues_formset = DuesFormSet(
            request.POST, queryset=dues_qs, prefix="dues",
        )
        tuition_formset = TuitionFormSet(
            request.POST, queryset=tuition_qs, prefix="tuition",
        )
        if dues_formset.is_valid() and tuition_formset.is_valid():
            with transaction.atomic():
                dues_formset.save()
                tuition_formset.save()
            return redirect(request.path + "?saved=1#saved")
    else:
        dues_formset = DuesFormSet(queryset=dues_qs, prefix="dues")
        tuition_formset = TuitionFormSet(queryset=tuition_qs, prefix="tuition")

    # Zip each form with its instance so the template can render the AY
    # name and date window alongside the editable fields.
    dues_rows = list(zip(dues_formset.forms, dues_qs))
    tuition_rows = list(zip(tuition_formset.forms, tuition_qs))

    return _treasurer_render(request, "settings", "payments/treasurer/settings.html", {
        "dues_formset":         dues_formset,
        "tuition_formset":      tuition_formset,
        "dues_rows":            dues_rows,
        "tuition_rows":         tuition_rows,
        "current_dues_period":  DuesPeriod.current(),
        "current_tuition_period": TuitionPeriod.current(),
        "saved":                request.GET.get("saved") == "1",
    })


def _treasurer_tuition_context() -> dict:
    """Build the tuition-section context for the treasurer dashboard (M7.5).

    Counts in-training users by enrollment status for the current
    TuitionPeriod, with a per-role breakdown, plus a list of undecided
    + committed-without-payment users (the reconciliation queue).
    """
    from accounts.models import Profile
    period = TuitionPeriod.current()
    if period is None:
        return {
            "tuition_period": None,
            "tuition_status_counts": [],
            "tuition_role_breakdown": [],
            "tuition_reconciliation_users": [],
            "tuition_in_training_count": 0,
            "tuition_total_collected": Decimal("0"),
        }

    in_training_qs = User.objects.filter(
        is_active=True, profile__role__in=Profile.IN_TRAINING_ROLES,
    )
    in_training_count = in_training_qs.count()

    enrollments = list(
        TuitionEnrollment.objects.filter(tuition_period=period)
        .select_related("user", "user__profile")
    )
    enrollment_by_user = {e.user_id: e for e in enrollments}

    # Count by status; undecided = in_training_count − (users with any enrollment).
    status_counter: dict[str, int] = {}
    for e in enrollments:
        status_counter[e.status] = status_counter.get(e.status, 0) + 1
    decided_user_ids = {e.user_id for e in enrollments}
    undecided_users = list(in_training_qs.exclude(id__in=decided_user_ids))

    # Display in a stable, lifecycle order.
    order = [
        ("paid_in_full",  "Paid in full"),
        ("payment_plan",  "On payment plan"),
        ("committed",     "Committed (unpaid)"),
        ("exempt",        "Exempt"),
        ("skipping",      "Skipping"),
    ]
    tuition_status_counts = [
        {"key": k, "label": label, "count": status_counter.get(k, 0)}
        for k, label in order
    ]
    tuition_status_counts.append(
        {"key": "undecided", "label": "Undecided", "count": len(undecided_users)}
    )

    # Per-role breakdown for the four in-training roles.
    role_labels = dict(Profile.Role.choices)
    role_breakdown_tuition = []
    for role in sorted(Profile.IN_TRAINING_ROLES):
        users_in_role = in_training_qs.filter(profile__role=role)
        total_in_role = users_in_role.count()
        in_role_user_ids = set(users_in_role.values_list("id", flat=True))
        decided_in_role = len(in_role_user_ids & decided_user_ids)
        # Reconciliation = undecided OR (decided with status=committed)
        committed_in_role = sum(
            1 for uid in in_role_user_ids
            if enrollment_by_user.get(uid) and
               enrollment_by_user[uid].status == TuitionEnrollment.Status.COMMITTED
        )
        role_breakdown_tuition.append({
            "role":           role,
            "role_label":     role_labels.get(role, role),
            "total":          total_in_role,
            "decided":        decided_in_role,
            "undecided":      total_in_role - decided_in_role,
            "committed_only": committed_in_role,
        })

    # Reconciliation list: undecided + committed-without-payment.
    reconciliation_users = []
    for u in undecided_users:
        reconciliation_users.append({
            "user":   u,
            "reason": "Undecided",
            "status": None,
        })
    for e in enrollments:
        if e.status == TuitionEnrollment.Status.COMMITTED:
            reconciliation_users.append({
                "user":   e.user,
                "reason": "Committed, no payment received",
                "status": e.status,
            })
    reconciliation_users.sort(
        key=lambda r: (r["user"].last_name or "", r["user"].first_name or "", r["user"].email)
    )

    # Total collected for the period — Payment of type=TUITION, succeeded,
    # linked to an installment whose enrollment is in this period.
    total_collected = (
        Payment.objects.filter(
            payment_type=Payment.Type.TUITION,
            status=Payment.Status.SUCCEEDED,
            tuition_installment__enrollment__tuition_period=period,
        )
        .aggregate(s=Sum("amount"))["s"] or Decimal("0")
    )

    return {
        "tuition_period":              period,
        "tuition_status_counts":       tuition_status_counts,
        "tuition_role_breakdown":      role_breakdown_tuition,
        "tuition_reconciliation_users": reconciliation_users,
        "tuition_in_training_count":   in_training_count,
        "tuition_total_collected":     total_collected,
    }


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning("Stripe webhook rejected: %s", exc)
        return HttpResponseBadRequest("Invalid signature.")

    event_type = event["type"]
    event_id = event["id"] if "id" in event else "?"
    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event["data"]["object"])
        elif event_type == "charge.refunded":
            _handle_charge_refunded(event["data"]["object"])
        else:
            logger.info("Stripe webhook ignored (type=%s id=%s)", event_type, event_id)
    except Exception:
        # Log the full traceback explicitly — Django's default LOGGING strips
        # it in production. Returning 500 tells Stripe to retry.
        logger.exception(
            "Stripe webhook handler failed (type=%s id=%s)", event_type, event_id
        )
        return HttpResponse("internal error", status=500)

    return HttpResponse(status=200)


def _handle_checkout_completed(session) -> None:
    """Idempotently mark the Payment + Registration as paid and issue a Receipt.

    ``session`` may be a plain dict (in tests) or a ``stripe.StripeObject``
    (in production). Both support bracket subscript and ``in`` membership,
    but ``StripeObject`` does *not* expose ``dict.get`` — use brackets only.
    """
    session_id = session["id"] if "id" in session else None
    if not session_id:
        logger.warning("checkout.session.completed without id; ignoring")
        return

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(
                stripe_checkout_session_id=session_id
            )
        except Payment.DoesNotExist:
            logger.warning(
                "No Payment for stripe_checkout_session_id=%s; ignoring", session_id
            )
            return

        if payment.status == Payment.Status.SUCCEEDED:
            return  # already processed — idempotent no-op

        # Stripe-specific bookkeeping — payment_intent goes onto the row
        # before we hand off to the generic success machinery.
        intent_id = session["payment_intent"] if "payment_intent" in session else None
        if intent_id:
            payment.stripe_payment_intent_id = intent_id
            payment.save(update_fields=("stripe_payment_intent_id",))

    # Run the shared success side-effects (idempotent across paths).
    complete_payment(payment)


@login_required
def dues_pay(request):
    """Membership dues entry point (REG-12) — tiered by role per DuesPeriod.

    Falls back to the per-tier defaults from settings if no period covers
    today (which shouldn't happen in production once the bootstrap data
    migration + auto-rollover command are running).
    """
    from .dues import user_paid_for_period
    from .models import DuesPeriod

    period = DuesPeriod.current()

    # Already paid for the current cycle — show a friendly status panel.
    if period is not None and user_paid_for_period(request.user, period):
        return render(
            request,
            "payments/dues_already_paid.html",
            {"period": period},
        )

    role = request.user.profile.role
    if period is not None:
        amount = period.amount_for_role(role)
    else:
        # No period configured — fall back to settings defaults.
        amount = _settings_dues_amount_for_role(role)

    if amount is None:
        # Role isn't on the dues tier table (e.g. external, member).
        return render(
            request,
            "payments/dues.html",
            {
                "amount": None, "period": period,
                "role_display": request.user.profile.get_role_display(),
            },
        )

    if request.method == "POST":
        payment = Payment.objects.create(
            payment_type=Payment.Type.DUES,
            user=request.user,
            amount=amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            dues_period=period,
        )
        session = create_dues_session(payment)
        return redirect(session.url)
    return render(
        request,
        "payments/dues.html",
        {"amount": amount, "period": period},
    )


def _settings_dues_amount_for_role(role: str) -> Decimal | None:
    """Fallback resolver when no DuesPeriod is configured."""
    field_to_setting = {
        "pre_candidate":         "DUES_PRE_CANDIDATE_AMOUNT",
        "pre_candidate_scholar": "DUES_PRE_CANDIDATE_AMOUNT",
        "candidate":             "DUES_CANDIDATE_AMOUNT",
        "candidate_scholar":     "DUES_CANDIDATE_AMOUNT",
        "analyst":               "DUES_ANALYST_AMOUNT",
        "scholar":               "DUES_ANALYST_AMOUNT",
    }
    setting_name = field_to_setting.get(role)
    if not setting_name:
        return None
    return Decimal(str(getattr(settings, setting_name)))


def donate(request):
    """Donation entry point (REG-13). Anonymous-friendly."""
    if request.method == "POST":
        form = DonationForm(request.POST, user=request.user)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            dedication = (form.cleaned_data.get("dedication") or "").strip()
            is_auth = request.user.is_authenticated
            email = request.user.email if is_auth else form.cleaned_data["email"]

            payment = Payment.objects.create(
                payment_type=Payment.Type.DONATION,
                user=request.user if is_auth else None,
                email="" if is_auth else email,
                amount=amount,
                method=Payment.Method.STRIPE,
                status=Payment.Status.PENDING,
                notes=dedication,
            )
            session = create_donation_session(payment, customer_email=email)
            return redirect(session.url)
    else:
        form = DonationForm(user=request.user)
    return render(request, "payments/donate.html", {"form": form})


@login_required
@user_passes_test(_is_staff)
def transactions_csv(request):
    """Staff-only CSV export of Payments (REG-15).

    Query params (all optional):
    - ``type``: comma-separated payment_type values to include
    - ``since``: ``YYYY-MM-DD`` lower bound on ``created_at`` (inclusive)
    - ``until``: ``YYYY-MM-DD`` upper bound on ``created_at`` (inclusive)
    """
    qs = (
        Payment.objects.select_related("user", "registration__event", "receipt")
        .order_by("created_at")
    )
    types_raw = (request.GET.get("type") or "").strip()
    if types_raw:
        types = [t.strip() for t in types_raw.split(",") if t.strip()]
        qs = qs.filter(payment_type__in=types)
    since = _parse_date(request.GET.get("since"))
    if since is not None:
        qs = qs.filter(created_at__date__gte=since)
    until = _parse_date(request.GET.get("until"))
    if until is not None:
        qs = qs.filter(created_at__date__lte=until)

    filename_bits = ["transactions"]
    if types_raw:
        filename_bits.append(types_raw.replace(",", "-"))
    if since:
        filename_bits.append(f"from-{since.isoformat()}")
    if until:
        filename_bits.append(f"to-{until.isoformat()}")
    filename = "-".join(filename_bits) + ".csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "id", "created_at", "paid_at", "payment_type", "amount", "currency",
        "status", "method", "user_email", "anonymous_email", "event_title",
        "receipt_number", "stripe_payment_intent_id",
        "stripe_checkout_session_id", "notes",
    ])
    for p in qs:
        writer.writerow([
            p.id,
            p.created_at.isoformat(),
            p.paid_at.isoformat() if p.paid_at else "",
            p.payment_type,
            p.amount,
            p.currency,
            p.status,
            p.method,
            p.user.email if p.user_id else "",
            p.email,
            (p.registration.event.title if p.registration_id else ""),
            (p.receipt.receipt_number if hasattr(p, "receipt") else ""),
            p.stripe_payment_intent_id,
            p.stripe_checkout_session_id,
            (p.notes or "").replace("\n", " | "),
        ])
    return response


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def payment_thanks(request, payment_id: int):
    """Generic post-Stripe thank-you page for non-registration payments.

    Doesn't require auth (anonymous donations need to reach it) and shows
    only generic info (type + amount + receipt number if available).
    """
    payment = get_object_or_404(
        Payment.objects.exclude(payment_type=Payment.Type.REGISTRATION),
        pk=payment_id,
    )
    return render(request, "payments/thanks.html", {"payment": payment})


def _handle_charge_refunded(charge: dict) -> None:
    """Idempotently mark Payment + Registration as REFUNDED.

    Fires for refunds we initiated synchronously (no-op since we already
    updated) and for refunds initiated directly in the Stripe Dashboard
    (the cross-channel case we actually need this for).
    """
    intent_id = charge["payment_intent"] if "payment_intent" in charge else None
    if not intent_id:
        return
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(
            stripe_payment_intent_id=intent_id,
        ).first()
        if payment is None:
            logger.info(
                "charge.refunded for unknown payment_intent=%s; ignoring", intent_id
            )
            return
        if payment.status != Payment.Status.REFUNDED:
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=("status",))
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.PAID,
            ).update(status=Registration.Status.REFUNDED)


@login_required
def tuition_decision(request):
    """Annual tuition decision page (M7.5).

    Open to authenticated users whose Profile.role is in the four
    in-training tracks (Profile.IN_TRAINING_ROLES). Posts create or
    update a TuitionEnrollment for the current TuitionPeriod.

    Shows the user their current decision status; lets them switch
    (committed / payment plan / skipping) before the period closes.
    """
    profile = request.user.profile
    if not profile.owes_tuition:
        return render(
            request, "payments/tuition_not_applicable.html",
            {"role_display": profile.get_role_display()},
        )

    period = TuitionPeriod.current()
    if period is None:
        return render(request, "payments/tuition_no_period.html")

    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()

    if request.method == "POST":
        form = TuitionDecisionForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data["status"]
            with transaction.atomic():
                enrollment, _ = TuitionEnrollment.objects.update_or_create(
                    user=request.user, tuition_period=period,
                    defaults={"status": status},
                )
            return redirect("tuition")
    else:
        initial = {"status": enrollment.status} if enrollment else {}
        form = TuitionDecisionForm(initial=initial)

    installments = []
    if enrollment is not None:
        installments = list(enrollment.installments.order_by("sequence"))

    return render(request, "payments/tuition.html", {
        "period":       period,
        "enrollment":   enrollment,
        "installments": installments,
        "form":         form,
        "stripe_status": request.GET.get("stripe"),
    })


@login_required
@require_POST
def tuition_pay_in_full(request):
    """Pay this year's tuition in a single Stripe transaction (M7.5).

    Creates a single TuitionInstallment for the full annual amount + a
    Payment + a Stripe Checkout Session, and redirects to Stripe. The
    webhook (or the treasurer's "Apply payment success" action) will
    flip the enrollment to PAID_IN_FULL via complete_payment.
    """
    profile = request.user.profile
    if not profile.owes_tuition:
        return redirect("tuition")
    period = TuitionPeriod.current()
    if period is None:
        return redirect("tuition")
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None:
        return redirect("tuition")
    if enrollment.installments.exists():
        # Already on a payment plan / has installments — direct to pay one
        # rather than minting a parallel "full" installment.
        return redirect("tuition")
    with transaction.atomic():
        installment = TuitionInstallment.objects.create(
            enrollment=enrollment, sequence=1,
            due_date=period.decision_due_date,
            amount=period.tuition_amount,
        )
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=request.user,
            amount=period.tuition_amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
        )
    session = create_tuition_session(payment)
    return redirect(session.url)


@login_required
@require_POST
def tuition_setup_plan(request):
    """Create the installment rows for a PAYMENT_PLAN enrollment (M7.5).

    Accepts ``installment_count`` of 2 (Sept + Feb) or 9 (monthly Sept–May).
    Idempotent: if installments already exist, redirects back without
    creating duplicates so a refresh of the POST doesn't multiply rows.
    """
    profile = request.user.profile
    if not profile.owes_tuition:
        return redirect("tuition")
    period = TuitionPeriod.current()
    if period is None:
        return redirect("tuition")
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None or enrollment.status != TuitionEnrollment.Status.PAYMENT_PLAN:
        return redirect("tuition")
    if enrollment.installments.exists():
        return redirect("tuition")
    try:
        count = int(request.POST.get("installment_count", "0"))
    except (TypeError, ValueError):
        return redirect("tuition")
    if count not in (2, 9):
        return redirect("tuition")

    schedule = _build_installment_schedule(period, count)
    with transaction.atomic():
        for seq, (due_date, amount) in enumerate(schedule, start=1):
            TuitionInstallment.objects.create(
                enrollment=enrollment, sequence=seq,
                due_date=due_date, amount=amount,
            )
    return redirect("tuition")


def _build_installment_schedule(
    period: TuitionPeriod, count: int,
) -> list[tuple[date, Decimal]]:
    """Return a list of ``(due_date, amount)`` tuples summing to tuition_amount.

    For ``count=2``: September (period.decision_due_date) and February.
    For ``count=9``: monthly from September through May.
    Rounding goes onto the final installment so the sum is exact.
    """
    from calendar import monthrange
    total = period.tuition_amount
    start_year = period.start_date.year

    def _last_day(year, month):
        return monthrange(year, month)[1]

    def _clamp(year, month, day=1):
        return date(year, month, min(day, _last_day(year, month)))

    if count == 2:
        # Sept (decision_due) + Feb of the following year (1st).
        dates = [period.decision_due_date, _clamp(start_year + 1, 2, 1)]
    elif count == 9:
        # Sept, Oct, Nov, Dec, Jan, Feb, Mar, Apr, May.
        months = [(start_year, 9), (start_year, 10), (start_year, 11),
                  (start_year, 12), (start_year + 1, 1), (start_year + 1, 2),
                  (start_year + 1, 3), (start_year + 1, 4), (start_year + 1, 5)]
        dates = [_clamp(y, m, 1) for y, m in months]
    else:
        return []

    base = (total / count).quantize(Decimal("0.01"))
    amounts = [base] * (count - 1)
    amounts.append(total - sum(amounts))  # remainder goes on the last
    return list(zip(dates, amounts))


@login_required
@require_POST
def tuition_pay_installment(request, installment_id: int):
    """Pay a specific tuition installment via Stripe (M7.5).

    Only the owning user can pay their installment. Re-paying a paid
    installment is a no-op redirect.
    """
    installment = get_object_or_404(
        TuitionInstallment.objects.select_related("enrollment"),
        pk=installment_id, enrollment__user=request.user,
    )
    if installment.paid:
        return redirect("tuition")
    with transaction.atomic():
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=request.user,
            amount=installment.amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
        )
    session = create_tuition_session(payment)
    return redirect(session.url)
