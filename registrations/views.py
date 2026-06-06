"""Public registration views (REG-1, REG-3, REG-4, REG-5, REG-16)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from events.models import Event, PriceTier, PricingCode
from events.permissions import can_edit_event
from payments import notifications as notify_payments
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
    """Return the covered-by-tuition tier that applies to a tuition-current user.

    Returns None unless the user is authenticated, is tuition-current for the
    active TuitionPeriod, and there's a covered_by_tuition tier matching their
    role (or ``all``).
    """
    profile = getattr(user, "profile", None) if user.is_authenticated else None
    if not (profile and profile.is_tuition_current()):
        return None
    qs = PriceTier.objects.filter(
        event=event, session__isnull=True, covered_by_tuition=True,
    )
    return qs.filter(audience=profile.role).first() or qs.filter(audience="all").first()


def _create_registration(
    *, request, event, tier, code, resolution
) -> Registration:
    requires_approval = event.requires_faculty_approval
    with transaction.atomic():
        if requires_approval:
            status = Registration.Status.PENDING_APPROVAL
        elif resolution.amount == Decimal("0"):
            status = Registration.Status.PAID
        else:
            status = Registration.Status.AWAITING_PAYMENT
        reg = Registration.objects.create(
            user=request.user,
            event=event,
            price_tier=tier,
            pricing_code=code,
            quoted_amount=resolution.amount,
            quoted_explanation=resolution.explanation,
            status=status,
        )
        # Consume the code now only for an immediately-active reg; the approval
        # flow consumes it on approval (a declined reg shouldn't burn a use).
        if code and code.max_uses is not None and not requires_approval:
            PricingCode.objects.filter(pk=code.pk).update(
                uses_remaining=F("uses_remaining") - 1
            )
    return reg


#: Event types where COMMITTED-but-unpaid additionally blocks registration
#: (M7.5). Only ``special_event`` for now — Days of Assembly, Working Days,
#: Scholarly Seminars all let COMMITTED students through. The set is a
#: deliberate config point; flip more event types in as the policy evolves.
TUITION_BLOCKING_EVENT_TYPES = frozenset({"special_event"})


def _tuition_block_reason(user, event) -> str | None:
    """Return a human-readable reason if the user is blocked from registering
    for this event due to unsettled-tuition status, or None to allow.

    Two-layer policy (M7.5):

    1. **Broad gate.** In-training students (pre-candidate / candidate /
       pre-candidate-scholar / candidate-scholar) who have not yet
       recorded a tuition decision for the current period are blocked
       from registering for *any* event. Some decision — even SKIPPING
       — must be on file before they can register for anything.

    2. **Narrow gate.** On top of layer 1, in-training students with
       status=COMMITTED (said they'll pay, but no payment received and
       no payment plan set up) are additionally blocked from event
       types in ``TUITION_BLOCKING_EVENT_TYPES``. This currently
       targets only ``special_event``; we may extend later. Other
       statuses (PAYMENT_PLAN, PAID_IN_FULL, SKIPPING) all
       pass — SKIPPING students pay the regular event fee.
    """
    profile = getattr(user, "profile", None)
    if not (profile and profile.owes_tuition):
        return None
    from payments.models import TuitionEnrollment, TuitionPeriod
    period = TuitionPeriod.current()
    if period is None:
        return None
    enr = profile.current_tuition_enrollment()
    if enr is None:
        return (
            "Before registering for any event, please record your tuition "
            f"decision for {period.name}. You'll be able to commit to pay, "
            "set up a payment plan, or note that you're skipping tuition "
            "this year — all options unlock registration."
        )
    if (event.event_type in TUITION_BLOCKING_EVENT_TYPES
            and enr.status == TuitionEnrollment.Status.COMMITTED
            and _find_covered_tier(user, event) is not None):
        # The student would be claiming tuition coverage they haven't paid
        # for. If the event has no covered_by_tuition tier matching their
        # audience, no coverage would apply — they'd pay the regular fee
        # like everyone else, so there's nothing to gate on.
        return (
            "You committed to pay tuition for "
            f"{period.name} but we haven't received a payment or a payment "
            "plan setup yet. Please complete payment, or switch to a payment "
            "plan, before registering for this special event."
        )
    return None


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

    # Tuition gate (M7.5) — block special-event registration for in-training
    # students who haven't recorded a tuition decision or are skipping the year.
    if (block_reason := _tuition_block_reason(request.user, event)) is not None:
        return render(
            request, "registrations/blocked_tuition.html",
            {"event": event, "reason": block_reason},
            status=403,
        )

    covered_tier = _find_covered_tier(request.user, event)

    # --- Tuition-covered short-circuit (REG-4) -----------------------
    if covered_tier and request.method == "POST" and request.POST.get("confirm_covered"):
        requires_approval = event.requires_faculty_approval
        reg = Registration.objects.create(
            user=request.user,
            event=event,
            price_tier=covered_tier,
            quoted_amount=Decimal("0"),
            quoted_explanation="Covered by tuition (tuition-paying member, REG-4).",
            status=(
                Registration.Status.PENDING_APPROVAL if requires_approval
                else Registration.Status.PAID
            ),
        )
        if requires_approval:
            notify_payments.registration_pending(reg)
        else:
            notify_payments.registration_confirmed(reg)
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

            if reg.status == Registration.Status.PENDING_APPROVAL:
                notify_payments.registration_pending(reg)   # notify faculty
                return redirect("registrations:confirm", reg_id=reg.id)

            if reg.quoted_amount == Decimal("0"):
                notify_payments.registration_confirmed(reg)
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
        notify_payments.registration_cancelled(reg, refund=refund)
    except Exception:
        logger.exception("Failed to send cancellation email for reg %s", reg.id)
        # Cancel went through; just log the email failure.

    return redirect(
        reverse("registrations:confirm", args=[reg.id]) + "?cancelled=1"
    )


def _safe_next(request, fallback: str) -> str:
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return fallback


@login_required
@require_POST
def approve_registration(request, reg_id: int):
    """Faculty approves a pending registration (→ awaiting payment, or paid if
    $0). Emails the registrant."""
    reg = get_object_or_404(Registration, pk=reg_id)
    if not can_edit_event(request.user, reg.event):
        return HttpResponseForbidden("You can't approve registrations for this event.")
    if reg.approve(request.user):
        if reg.needs_payment:
            notify_payments.registration_approved(reg)   # "approved — pay to confirm"
        else:
            notify_payments.registration_confirmed(reg)  # $0 / covered → confirmed + access
    return redirect(_safe_next(request, reverse("registrations:confirm", args=[reg.id])))


@login_required
@require_POST
def decline_registration(request, reg_id: int):
    """Faculty declines a pending registration. Emails the registrant."""
    reg = get_object_or_404(Registration, pk=reg_id)
    if not can_edit_event(request.user, reg.event):
        return HttpResponseForbidden("You can't decline registrations for this event.")
    if reg.decline(request.user, (request.POST.get("reason") or "").strip()):
        notify_payments.registration_declined(reg)
    return redirect(_safe_next(request, reverse("registrations:confirm", args=[reg.id])))


@login_required
@require_POST
def pay_registration(request, reg_id: int):
    """The registrant starts (or resumes) Stripe Checkout for an approved /
    awaiting-payment registration."""
    reg = get_object_or_404(Registration, pk=reg_id, user=request.user)
    if not reg.needs_payment:
        return redirect("registrations:confirm", reg_id=reg.id)
    _payment, session = create_checkout_session(reg)
    return redirect(session.url)
