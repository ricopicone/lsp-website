"""The Board's tuition payment-plan review queue (task #450 phase B).

A member's application for a Board-approved payment plan
(``TuitionPlanApplication``, PENDING/APPROVED/DECLINED) is reviewed here.
Approving moves the member's ``TuitionEnrollment`` for that period to
PAYMENT_PLAN; declining reverts it (deletes the PLAN_REQUESTED row) to
no-decision so the member can choose to pay in full or skip the year.
Gated to superusers and active Board members — everyone else follows the
``core.access.gate_or_login`` convention (anonymous → login redirect,
signed-in non-Board → 404).
"""

from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from committees.permissions import is_on_committee
from core.access import gate_or_login

from .models import TuitionEnrollment, TuitionPlanApplication
from .notifications import notify_plan_application_decided


def _can_review(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and (
        user.is_superuser or is_on_committee(user, "board")
    )


def tuition_plan_queue(request):
    """Pending applications first, then decided history."""
    if not _can_review(request.user):
        return gate_or_login(request)

    applications = (
        TuitionPlanApplication.objects
        .select_related("user", "user__profile", "tuition_period", "decided_by")
        .order_by("-created_at")
    )
    pending = [
        a for a in applications if a.status == TuitionPlanApplication.Status.PENDING
    ]
    decided = [
        a for a in applications if a.status != TuitionPlanApplication.Status.PENDING
    ]
    return render(request, "payments/tuition_plan_queue.html", {
        "pending": pending,
        "decided": decided,
    })


def tuition_plan_decide(request, pk):
    """POST ``action=approve|decline`` (+ optional ``note``). Only a PENDING
    application can be decided — deciding twice is a no-op error."""
    if not _can_review(request.user):
        return gate_or_login(request)

    application = get_object_or_404(TuitionPlanApplication, pk=pk)
    if request.method != "POST":
        return redirect("tuition_plan_queue")

    if application.status != TuitionPlanApplication.Status.PENDING:
        messages.error(request, "This application has already been decided.")
        return redirect("tuition_plan_queue")

    action = request.POST.get("action")
    note = (request.POST.get("note") or "").strip()
    if action not in ("approve", "decline"):
        messages.error(request, "Choose approve or decline.")
        return redirect("tuition_plan_queue")

    with transaction.atomic():
        if action == "approve":
            application.status = TuitionPlanApplication.Status.APPROVED
            # update_or_create — the PLAN_REQUESTED row should exist (the
            # member's request created it) but don't crash if it's gone
            # (e.g. the member deleted/changed their decision meanwhile).
            TuitionEnrollment.objects.update_or_create(
                user=application.user, tuition_period=application.tuition_period,
                defaults={"status": TuitionEnrollment.Status.PAYMENT_PLAN},
            )
        else:
            application.status = TuitionPlanApplication.Status.DECLINED
            # Only unwind the enrollment if it's still the PLAN_REQUESTED row
            # this application produced — a member may have since recorded a
            # different decision, which decline must not clobber.
            TuitionEnrollment.objects.filter(
                user=application.user, tuition_period=application.tuition_period,
                status=TuitionEnrollment.Status.PLAN_REQUESTED,
            ).delete()
        application.decided_by = request.user
        application.decided_at = timezone.now()
        application.note = note
        application.save(
            update_fields=["status", "decided_by", "decided_at", "note"],
        )

    notify_plan_application_decided(application)

    verb = "Approved" if action == "approve" else "Declined"
    messages.success(
        request, f"{verb} the payment-plan application; the member has been notified.",
    )
    return redirect("tuition_plan_queue")
