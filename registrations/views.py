"""Public registration views (REG-1, REG-3, REG-4, REG-5, REG-16)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from events.models import Event, PriceTier, PricingCode
from payments.emails import send_cancellation_email, send_registration_confirmation
from payments.refund import RefundError
from payments.stripe_checkout import create_checkout_session

from .forms import RegistrationForm
from .models import Registration

logger = logging.getLogger(__name__)


def _existing_active_registration(user, event):
    """Return the user's existing active Registration for this event, or None."""
    if not user.is_authenticated:
        return None
    return (
        Registration.objects.filter(user=user, event=event)
        .exclude(
            status__in=(
                Registration.Status.CANCELLED,
                Registration.Status.REFUNDED,
            )
        )
        .first()
    )


def _find_covered_tier(user, event: Event) -> PriceTier | None:
    """Return the covered-by-tuition tier that applies to a tuition-paying user.

    Returns None unless the user is authenticated, has ``tuition_paying=True``,
    and there's a covered_by_tuition tier matching their role (or ``all``).
    """
    profile = getattr(user, "profile", None) if user.is_authenticated else None
    if not (profile and profile.tuition_paying):
        return None
    qs = PriceTier.objects.filter(
        event=event, session__isnull=True, covered_by_tuition=True,
    )
    return qs.filter(audience=profile.role).first() or qs.filter(audience="all").first()


def _create_registration(
    *, request, event, tier, code, resolution
) -> Registration:
    with transaction.atomic():
        reg = Registration.objects.create(
            user=request.user,
            event=event,
            price_tier=tier,
            pricing_code=code,
            quoted_amount=resolution.amount,
            quoted_explanation=resolution.explanation,
            status=(
                Registration.Status.PAID
                if resolution.amount == Decimal("0")
                else Registration.Status.AWAITING_PAYMENT
            ),
        )
        if code and code.max_uses is not None:
            PricingCode.objects.filter(pk=code.pk).update(
                uses_remaining=F("uses_remaining") - 1
            )
    return reg


@login_required
def register_for_event(request, event_slug: str):
    event = get_object_or_404(Event, slug=event_slug)
    if not (event.published and event.status == Event.Status.OPEN):
        raise Http404("Registration not open for this event.")

    # Already-registered short-circuit: redirect to the existing reg's
    # confirmation page with a notice. Prevents the IntegrityError that
    # `registrations_one_active_per_user_event` would otherwise raise on
    # duplicate inserts (data migration 0002 cleaned up any pre-existing
    # duplicates).
    existing = _existing_active_registration(request.user, event)
    if existing is not None:
        return redirect(
            reverse("registrations:confirm", args=[existing.id]) + "?already=1"
        )

    covered_tier = _find_covered_tier(request.user, event)

    # --- Tuition-covered short-circuit (REG-4) -----------------------
    if covered_tier and request.method == "POST" and request.POST.get("confirm_covered"):
        reg = Registration.objects.create(
            user=request.user,
            event=event,
            price_tier=covered_tier,
            quoted_amount=Decimal("0"),
            quoted_explanation="Covered by tuition (tuition-paying member, REG-4).",
            status=Registration.Status.PAID,
        )
        send_registration_confirmation(reg)
        return redirect("registrations:confirm", reg_id=reg.id)

    if covered_tier and request.method == "GET":
        return render(
            request,
            "registrations/register_covered.html",
            {"event": event, "tier": covered_tier},
        )

    # --- Standard form path ------------------------------------------
    if request.method == "POST":
        form = RegistrationForm(request.POST, event=event, user=request.user)
        if form.is_valid():
            resolution = form.cleaned_data["resolution"]
            code = form.cleaned_data.get("pricing_code_obj")
            reg = _create_registration(
                request=request, event=event,
                tier=form.cleaned_data["price_tier"],
                code=code, resolution=resolution,
            )

            if reg.quoted_amount == Decimal("0"):
                send_registration_confirmation(reg)
                return redirect("registrations:confirm", reg_id=reg.id)

            _payment, session = create_checkout_session(reg)
            return redirect(session.url)
    else:
        form = RegistrationForm(event=event, user=request.user)

    # Per-tier slider config exposed to the template (and the small JS that
    # syncs the slider + number input + show/hide of the sliding block).
    tiers_meta = {
        str(t.pk): {
            "sliding": t.sliding_scale,
            "min": str(t.minimum_amount if t.minimum_amount is not None else 0),
            "max": str(t.base_amount),
        }
        for t in PriceTier.objects.filter(event=event, session__isnull=True)
    }

    return render(
        request,
        "registrations/register.html",
        {
            "event": event,
            "form": form,
            "tiers_meta_json": json.dumps(tiers_meta),
        },
    )


@login_required
def registration_confirm(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id, user=request.user)
    return render(
        request,
        "registrations/register_confirm.html",
        {"registration": reg},
    )


@login_required
@require_POST
def cancel_registration(request, reg_id: int):
    """Self-cancel a Registration; refund via Stripe if PAID (REG-16)."""
    reg = get_object_or_404(Registration, pk=reg_id, user=request.user)
    if reg.status in (Registration.Status.CANCELLED, Registration.Status.REFUNDED):
        # Idempotent — the cancel button shouldn't render in this state, but
        # someone may be re-posting an old form.
        return redirect("registrations:confirm", reg_id=reg.id)

    refund = None
    try:
        refund = reg.cancel()
    except RefundError as exc:
        # Could not auto-refund (offline payment, missing intent, etc.).
        logger.warning("Cancel failed for reg %s: %s", reg.id, exc)
        messages.error(
            request,
            "We couldn't process the refund automatically — please contact the "
            "Web Coordinator and they'll handle it.",
        )
        return redirect("registrations:confirm", reg_id=reg.id)
    except Exception:
        logger.exception("Unexpected error cancelling reg %s", reg.id)
        messages.error(
            request,
            "Something went wrong cancelling your registration. The Web "
            "Coordinator has been notified.",
        )
        return redirect("registrations:confirm", reg_id=reg.id)

    try:
        send_cancellation_email(reg, refund=refund)
    except Exception:
        logger.exception("Failed to send cancellation email for reg %s", reg.id)
        # Cancel went through; just log the email failure.

    return redirect(
        reverse("registrations:confirm", args=[reg.id]) + "?cancelled=1"
    )
