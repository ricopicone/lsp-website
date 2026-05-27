"""Public registration views (REG-1, REG-3, REG-5)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from events.models import Event, PricingCode
from payments.emails import send_registration_confirmation
from payments.stripe_checkout import create_checkout_session

from .forms import RegistrationForm
from .models import Registration


@login_required
def register_for_event(request, event_slug: str):
    event = get_object_or_404(Event, slug=event_slug)
    if not (event.published and event.status == Event.Status.OPEN):
        raise Http404("Registration not open for this event.")

    if request.method == "POST":
        form = RegistrationForm(request.POST, event=event, user=request.user)
        if form.is_valid():
            resolution = form.cleaned_data["resolution"]
            code = form.cleaned_data.get("pricing_code_obj")
            with transaction.atomic():
                reg = Registration.objects.create(
                    user=request.user,
                    event=event,
                    price_tier=form.cleaned_data["price_tier"],
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

            # $0 registrations skip Stripe entirely but still get the
            # confirmation + access_info email (REG-8 / REG-9).
            if reg.quoted_amount == Decimal("0"):
                send_registration_confirmation(reg)
                return redirect("registrations:confirm", reg_id=reg.id)

            # Otherwise hand off to Stripe Checkout.
            _payment, session = create_checkout_session(reg)
            return redirect(session.url)
    else:
        form = RegistrationForm(event=event, user=request.user)

    return render(
        request,
        "registrations/register.html",
        {"event": event, "form": form},
    )


@login_required
def registration_confirm(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id, user=request.user)
    return render(
        request,
        "registrations/register_confirm.html",
        {"registration": reg},
    )
