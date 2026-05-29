"""Public payment views: webhook, dues, donations, thanks, exports, dashboard."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registrations.models import Registration

from .forms import DonationForm, TuitionDecisionForm
from .models import DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod
from .operations import complete_payment
from .stripe_checkout import create_donation_session, create_dues_session

logger = logging.getLogger(__name__)
User = get_user_model()


def _is_staff(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_is_staff)
def treasurer_dashboard(request):
    """Per-period dues + tuition summary, role breakdowns, multi-period totals."""
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

    # JSON payloads for Chart.js.
    chart_periods = {
        "labels": [s["period"].name for s in reversed(period_stats)],
        "totals": [float(s["total_collected"]) for s in reversed(period_stats)],
    }
    chart_roles = {
        "labels": [r["role"] for r in role_breakdown],
        "paid": [r["paid"] for r in role_breakdown],
        "unpaid": [r["unpaid"] for r in role_breakdown],
    }

    tuition_ctx = _treasurer_tuition_context()

    return render(request, "payments/treasurer.html", {
        "period_stats": period_stats,
        "current_period": current,
        "role_breakdown": role_breakdown,
        "unpaid_users": unpaid_users,
        "obligated_count": obligated_count,
        "chart_periods_json": json.dumps(chart_periods),
        "chart_roles_json": json.dumps(chart_roles),
        **tuition_ctx,
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
    """Membership dues entry point (REG-12) — uses the current DuesPeriod.

    Falls back to the ``DUES_ANNUAL_AMOUNT`` setting if no period covers
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

    amount = period.dues_amount if period else Decimal(str(settings.DUES_ANNUAL_AMOUNT))

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

    return render(request, "payments/tuition.html", {
        "period":     period,
        "enrollment": enrollment,
        "form":       form,
    })
