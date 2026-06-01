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
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import is_lsp_member
from events.permissions import is_program_committee

from . import emails
from .forms import CartelProposalForm
from .models import Cartel, CartelInvitation, CartelJoinRequest, ExternalPlusOne
from .permissions import is_cartel_coordinator


def _abs(request, obj):
    return request.build_absolute_uri(obj.get_absolute_url())


def index(request):
    """Cartels are browsed under the unified Groups section now."""
    return redirect("workgroups:kind_cartels")


def detail(request, slug):
    """The cartel's canonical page is the (kind-aware) Workgroup detail."""
    return redirect("workgroups:detail", slug=slug)


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
            emails.notify_proposal(cartel, _abs(request, cartel))
            messages.success(
                request,
                "Cartel proposed. The Cartel Coordinator (for feedback) and the "
                "Program Committee (for approval) have been notified.",
            )
            return redirect(cartel.get_absolute_url())
    else:
        form = CartelProposalForm()
    return render(request, "cartels/propose.html", {"form": form})


@login_required
def review_queue(request):
    """Proposed-cartel queue. The Program Committee approves/declines; the
    Cartel Coordinator advises (feedback/advocacy) in parallel."""
    can_approve = is_program_committee(request.user)
    can_feedback = is_cartel_coordinator(request.user)
    if not (can_approve or can_feedback):
        raise Http404
    proposed = (
        Cartel.objects.filter(status=Cartel.Status.PROPOSED)
        .select_related("workgroup", "generator")
        .order_by("created_at")
    )
    return render(request, "cartels/review_queue.html", {
        "proposed": proposed,
        "can_approve": can_approve,
        "can_feedback": can_feedback,
    })


@login_required
@require_POST
def review_decide(request, pk):
    """The Program Committee approves (publishes) or declines a proposal."""
    if not is_program_committee(request.user):
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
@require_POST
def coordinator_feedback(request, pk):
    """The Cartel Coordinator records feedback / advocacy (advisory — does not
    gate; the PC approves). Notifies the generator + the PC."""
    if not is_cartel_coordinator(request.user):
        raise Http404
    cartel = get_object_or_404(Cartel, pk=pk)
    cartel.coordinator_feedback = (request.POST.get("feedback") or "").strip()
    cartel.save(update_fields=["coordinator_feedback"])
    if cartel.coordinator_feedback:
        emails.notify_coordinator_feedback(cartel, _abs(request, cartel))
    messages.success(request, f"Feedback recorded for '{cartel.workgroup.name}'.")
    return redirect("cartels:review_queue")


@login_required
@require_POST
def apply(request, slug):
    """A member applies to join an open cartel (CART-4 step 5), with a note."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug, status=Cartel.Status.OPEN)
    if not is_lsp_member(request.user) or cartel.closed or cartel.is_member(request.user):
        raise Http404
    cartel.request_to_join(request.user, message=(request.POST.get("message") or "").strip())
    emails.notify_members_of_application(cartel, request.user, _abs(request, cartel))
    messages.success(request, "Application sent — a member of the cartel will review it.")
    return redirect(cartel.get_absolute_url())


@login_required
def edit(request, slug):
    """The Generator edits a proposed/declined cartel; saving a declined one
    re-submits it for fresh Coordinator review (improvement 1)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    editable = cartel.status in (Cartel.Status.PROPOSED, Cartel.Status.DECLINED)
    if request.user != cartel.generator or not editable:
        raise Http404
    if request.method == "POST":
        form = CartelProposalForm(request.POST)
        if form.is_valid():
            wg = cartel.workgroup
            wg.name = form.cleaned_data["name"]
            wg.description = form.cleaned_data["description"]
            wg.save(update_fields=["name", "description"])
            cartel.guiding_question = form.cleaned_data["guiding_question"]
            cartel.save(update_fields=["guiding_question"])
            for user in form.cleaned_data["invitees"]:
                CartelInvitation.objects.get_or_create(cartel=cartel, invited_user=user)
            if cartel.status == Cartel.Status.DECLINED:
                cartel.resubmit()
                emails.notify_proposal(cartel, _abs(request, cartel))
                messages.success(request, "Edited and resubmitted for review.")
            else:
                messages.success(request, "Proposal updated.")
            return redirect(cartel.get_absolute_url())
    else:
        form = CartelProposalForm(initial={
            "name": cartel.workgroup.name,
            "guiding_question": cartel.guiding_question,
            "description": cartel.workgroup.description,
        })
    return render(request, "cartels/edit.html", {"cartel": cartel, "form": form})


@login_required
@require_POST
def manage(request, slug):
    """A member closes/reopens the cartel to new members, or archives it."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    action = request.POST.get("action")
    if action == "close":
        cartel.set_closed(True)
    elif action == "reopen":
        cartel.set_closed(False)
    elif action == "archive":
        cartel.archive()
    return redirect(f"{cartel.get_absolute_url()}?tab=settings")


def _settings_redirect(cartel):
    return redirect(f"{cartel.get_absolute_url()}?tab=settings")


@login_required
@require_POST
def set_plus_one(request, slug):
    """Designate an existing member as the (internal) plus-one."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    from accounts.models import User

    member = get_object_or_404(
        User, pk=request.POST.get("user"),
        workgroup_memberships__workgroup=cartel.workgroup,
        workgroup_memberships__end_date__isnull=True,
    )
    cartel.set_internal_plus_one(member)
    return _settings_redirect(cartel)


@login_required
@require_POST
def add_external_plus_one(request, slug):
    """Record an external (non-LSP) plus-one."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    name = (request.POST.get("name") or "").strip()
    if name:
        ExternalPlusOne.objects.create(
            cartel=cartel,
            name=name[:200],
            affiliation=(request.POST.get("affiliation") or "").strip()[:200],
            email=(request.POST.get("email") or "").strip(),
        )
        messages.success(request, f"Added external plus-one {name}.")
    return _settings_redirect(cartel)


@login_required
@require_POST
def invite_external_plus_one(request, slug, pk):
    """Invite an external plus-one to create an LSP account."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    ext = get_object_or_404(ExternalPlusOne, pk=pk, cartel=cartel)
    if ext.email:
        signup_url = request.build_absolute_uri(reverse("signup"))
        emails.invite_external_plus_one(ext, signup_url)
        ext.invited_at = timezone.now()
        ext.save(update_fields=["invited_at"])
        messages.success(request, f"Invited {ext.name} to create an account.")
    else:
        messages.error(request, f"{ext.name} has no email on file.")
    return _settings_redirect(cartel)


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
