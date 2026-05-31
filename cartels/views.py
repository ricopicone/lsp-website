"""Cartels — public list + the CART-4 formation/joining workflow views.

Thin views over the workflow methods on ``Cartel`` (see models.py). Member
gating uses the Workgroup roster; coordinator gating uses
``is_cartel_coordinator``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import is_lsp_member

from . import emails
from .forms import CartelProposalForm
from .models import Cartel, CartelJoinRequest
from .permissions import is_cartel_coordinator


def _abs(request, obj):
    return request.build_absolute_uri(obj.get_absolute_url())


def index(request):
    """Public list of cartels visible to the user (PROPOSED stay hidden)."""
    cartels = [
        c for c in Cartel.objects.select_related("workgroup")
        if c.workgroup.landing_visible_to(request.user)
    ]
    return render(request, "cartels/index.html", {
        "cartels": cartels,
        "can_propose": is_lsp_member(request.user),
        "is_coordinator": is_cartel_coordinator(request.user),
    })


@login_required
def propose(request):
    """A member proposes a cartel (CART-4 step 1)."""
    if not is_lsp_member(request.user):
        raise Http404
    if request.method == "POST":
        form = CartelProposalForm(request.POST)
        if form.is_valid():
            cartel = Cartel.objects.propose(
                generator=request.user,
                name=form.cleaned_data["name"],
                guiding_question=form.cleaned_data["guiding_question"],
                description=form.cleaned_data["description"],
                invitees=form.cleaned_data["invitees"],
            )
            emails.notify_coordinator_of_proposal(cartel, _abs(request, cartel))
            messages.success(
                request,
                "Cartel proposed. The Cartel Coordinator will review it before it's "
                "published.",
            )
            return redirect(cartel.get_absolute_url())
    else:
        form = CartelProposalForm()
    return render(request, "cartels/propose.html", {"form": form})


@login_required
def review_queue(request):
    """Coordinator's queue of proposed cartels."""
    if not is_cartel_coordinator(request.user):
        raise Http404
    proposed = (
        Cartel.objects.filter(status=Cartel.Status.PROPOSED)
        .select_related("workgroup", "generator")
        .order_by("created_at")
    )
    return render(request, "cartels/review_queue.html", {"proposed": proposed})


@login_required
@require_POST
def review_decide(request, pk):
    """Coordinator approves or declines a proposed cartel."""
    if not is_cartel_coordinator(request.user):
        raise Http404
    cartel = get_object_or_404(Cartel, pk=pk, status=Cartel.Status.PROPOSED)
    if request.POST.get("decision") == "approve":
        cartel.approve(request.user)
        emails.notify_generator_of_decision(cartel, _abs(request, cartel))
        for inv in cartel.invitations.all():
            emails.notify_invitee(cartel, inv.invited_user, _abs(request, cartel))
        messages.success(request, f"Approved '{cartel.workgroup.name}'.")
    else:
        cartel.decline(request.user, note=request.POST.get("note", ""))
        emails.notify_generator_of_decision(cartel, _abs(request, cartel))
        messages.success(request, f"Declined '{cartel.workgroup.name}'.")
    return redirect("cartels:review_queue")


@login_required
def detail(request, slug):
    """A cartel's page: guiding question, roster, apply + member-gating."""
    cartel = get_object_or_404(Cartel.objects.select_related("workgroup"), workgroup__slug=slug)
    wg = cartel.workgroup
    if not wg.landing_visible_to(request.user):
        raise Http404
    user = request.user
    is_member = cartel.is_member(user)
    pending = (
        cartel.join_requests.filter(status=CartelJoinRequest.Status.PENDING)
        .select_related("applicant") if is_member else []
    )
    has_invite = cartel.invitations.filter(
        invited_user=user, accepted_at__isnull=True
    ).exists()
    already_applied = cartel.join_requests.filter(
        applicant=user, status=CartelJoinRequest.Status.PENDING
    ).exists()
    can_apply = (
        cartel.status == Cartel.Status.OPEN and not cartel.closed
        and is_lsp_member(user) and not is_member and not has_invite and not already_applied
    )
    return render(request, "cartels/detail.html", {
        "cartel": cartel,
        "workgroup": wg,
        "members": list(wg.active_members()) if wg.content_visible_to(user) else [],
        "is_member": is_member,
        "pending_requests": pending,
        "has_invite": has_invite,
        "already_applied": already_applied,
        "can_apply": can_apply,
        "channel": wg.channels.first() if is_member else None,
        "is_coordinator": is_cartel_coordinator(user),
    })


@login_required
@require_POST
def apply(request, slug):
    """A member applies to join an open cartel (CART-4 step 5)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug, status=Cartel.Status.OPEN)
    if not is_lsp_member(request.user) or cartel.closed or cartel.is_member(request.user):
        raise Http404
    cartel.request_to_join(request.user)
    emails.notify_members_of_application(cartel, request.user, _abs(request, cartel))
    messages.success(request, "Application sent — a member of the cartel will review it.")
    return redirect(cartel.get_absolute_url())


@login_required
@require_POST
def accept_invitation(request, slug):
    """A seeded invitee accepts and joins directly."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug, status=Cartel.Status.OPEN)
    if cartel.accept_invitation(request.user) is None:
        raise Http404
    messages.success(request, f"You've joined '{cartel.workgroup.name}'.")
    return redirect(cartel.get_absolute_url())


@login_required
@require_POST
def decide_request(request, slug, pk):
    """An existing member accepts/declines an applicant (member-gated growth)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    join_request = get_object_or_404(
        CartelJoinRequest, pk=pk, cartel=cartel, status=CartelJoinRequest.Status.PENDING
    )
    if request.POST.get("decision") == "accept":
        cartel.accept_request(join_request, decided_by=request.user)
    else:
        cartel.decline_request(join_request, decided_by=request.user)
    emails.notify_applicant_of_decision(join_request, _abs(request, cartel))
    return redirect(cartel.get_absolute_url())
