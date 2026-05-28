"""Public payment views: webhook, dues, donations, thanks, exports."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registrations.models import Registration

from .emails import send_paid_emails, send_payment_receipt
from .forms import DonationForm
from .models import Payment, Receipt
from .stripe_checkout import create_donation_session, create_dues_session

logger = logging.getLogger(__name__)


def _is_staff(user):
    return user.is_authenticated and user.is_staff


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

        payment.mark_succeeded()
        intent_id = session["payment_intent"] if "payment_intent" in session else None
        if intent_id:
            payment.stripe_payment_intent_id = intent_id
            payment.save(update_fields=("stripe_payment_intent_id",))

        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id
            ).update(status=Registration.Status.PAID)

        if not hasattr(payment, "receipt"):
            Receipt.create_for_payment(payment)

    # Send emails *after* the transaction commits so we never report success
    # via email for a write that rolls back. Email failures (e.g. SES sandbox
    # rejecting an unverified recipient) must NOT roll back the DB updates or
    # cause Stripe to retry — log and move on.
    try:
        if payment.registration_id:
            payment.registration.refresh_from_db()
            send_paid_emails(payment.registration)
        else:
            # Dues / donation — receipt is the only email these get.
            send_payment_receipt(payment)
    except Exception:
        logger.exception(
            "Failed to send post-payment emails for payment %s; "
            "DB updates retained.",
            payment.id,
        )


@login_required
def dues_pay(request):
    """Membership dues entry point (REG-12). Fixed annual amount."""
    amount = Decimal(settings.DUES_ANNUAL_AMOUNT)
    if request.method == "POST":
        payment = Payment.objects.create(
            payment_type=Payment.Type.DUES,
            user=request.user,
            amount=amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
        )
        session = create_dues_session(payment)
        return redirect(session.url)
    return render(request, "payments/dues.html", {"amount": amount})


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
