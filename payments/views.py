"""Webhook handler for Stripe events (architecture § 6.3).

Stripe POSTs ``checkout.session.completed`` and related events to our
endpoint. We verify the signature with ``STRIPE_WEBHOOK_SECRET``, look
up the ``Payment`` row by ``stripe_checkout_session_id`` (the natural
idempotency key), and on a fresh successful event:

1. mark the Payment ``SUCCEEDED`` (and set ``paid_at``);
2. mark the Registration ``PAID``;
3. create a ``Receipt``;
4. (M4 step D) email the receipt + confirmation and release access_info.

Repeats of the same event do nothing. Unknown event types are no-ops.
Errors return 400 (Stripe will retry); successful handling returns 200.
"""

from __future__ import annotations

import logging

import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registrations.models import Registration

from .emails import send_paid_emails
from .models import Payment, Receipt

logger = logging.getLogger(__name__)


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
    event_id = event.get("id", "?")
    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event["data"]["object"])
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


def _handle_checkout_completed(session: dict) -> None:
    """Idempotently mark the Payment + Registration as paid and issue a Receipt."""
    session_id = session.get("id")
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
            # Already processed — idempotent no-op.
            return

        payment.mark_succeeded()
        if intent_id := session.get("payment_intent"):
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
    if payment.registration_id:
        payment.registration.refresh_from_db()
        try:
            send_paid_emails(payment.registration)
        except Exception:
            logger.exception(
                "Failed to send paid-registration emails for payment %s; "
                "DB updates retained.",
                payment.id,
            )
