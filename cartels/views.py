"""Cartels — public list + the CART-4 formation/joining workflow views.

Thin views over the workflow methods on ``Cartel`` (see models.py). Member
gating uses the Workgroup roster; coordinator gating uses
``is_cartel_coordinator``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import is_lsp_member
from events.permissions import is_program_committee

from . import notifications as notify_cartels
from .forms import CartelProposalForm, CartelStartForm
from .models import Cartel, CartelJoinRequest, CartelQuestion, ExternalPlusOne
from .permissions import is_cartel_coordinator


def _abs(request, obj):
    return request.build_absolute_uri(obj.get_absolute_url())


def _selected_invitees(form):
    """The invitee Users to preload as picker chips: from a bound form's
    submitted PKs (so an invalid POST keeps the chosen list), else empty."""
    if not form.is_bound:
        return []
    ids = form.data.getlist("invitees")
    return list(get_user_model().objects.filter(pk__in=ids)) if ids else []


@login_required
def member_search(request):
    """Directory-member autocomplete for the invitee picker. Returns id + name."""
    if not is_lsp_member(request.user):
        raise Http404
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})
    from accounts.models import Profile

    User = get_user_model()
    qs = User.objects.filter(
        profile__role__in=Profile.DIRECTORY_ROLES
    ).exclude(pk=request.user.pk)
    for term in q.split()[:3]:
        qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
    results = [
        {"id": u.pk, "name": u.get_full_name() or u.email}
        for u in qs.order_by("first_name", "last_name")[:8]
    ]
    return JsonResponse({"results": results})


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
        form = CartelStartForm(request.POST)
        if form.is_valid():
            cartel = Cartel.objects.propose(
                generator=request.user,
                name=form.cleaned_data["name"],
                theme=form.cleaned_data["theme"],
                description=form.cleaned_data["description"],
                invitees=form.cleaned_data["invitees"],
                closed=form.cleaned_data["closed"],
            )
            notify_cartels.forming_started(cartel, _abs(request, cartel))
            for inv in cartel.invitations.all():
                notify_cartels.invitee(cartel, inv.invited_user, _abs(request, cartel))
            messages.success(
                request,
                "Your cartel is now forming and visible to the school. Invite "
                "members, then submit it to the Programming Committee to register.",
            )
            return redirect(cartel.get_absolute_url())
    else:
        form = CartelStartForm()
    return render(request, "cartels/propose.html", {
        "form": form, "selected_invitees": _selected_invitees(form),
    })


@login_required
@require_POST
def submit(request, slug):
    """Any cartelisand submits the cartel to the PC for registration."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    if cartel.registration_status != Cartel.RegistrationStatus.FORMING:
        messages.info(
            request,
            "This cartel has already been submitted or registered.",
        )
        return redirect(cartel.get_absolute_url())
    try:
        cartel.submit_for_registration(by=request.user)
    except ValidationError:
        messages.error(
            request,
            "This cartel isn't ready to register yet. Check the formation "
            "checklist: a plus-one, a fixed period of 1 to 2 years, and 3 to 5 "
            "cartelisands are required.",
        )
        return redirect(cartel.get_absolute_url())
    notify_cartels.submitted(cartel, _abs(request, cartel))
    messages.success(
        request,
        "Submitted to the Programming Committee for registration. They have been notified.",
    )
    return redirect(cartel.get_absolute_url())


@login_required
@require_POST
def set_question(request, slug):
    """A cartelisand records or updates their own question."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    CartelQuestion.objects.update_or_create(
        cartel=cartel, member=request.user,
        defaults={"text": (request.POST.get("text") or "").strip()},
    )
    messages.success(request, "Your question has been saved.")
    return redirect(cartel.get_absolute_url())


@login_required
def review_queue(request):
    """Proposed-cartel queue. The Program Committee approves/declines; the
    Cartel Coordinator advises (feedback/advocacy) in parallel."""
    can_approve = is_program_committee(request.user)
    can_feedback = is_cartel_coordinator(request.user)
    if not (can_approve or can_feedback):
        raise Http404
    submitted = (
        Cartel.objects.filter(registration_status=Cartel.RegistrationStatus.SUBMITTED)
        .select_related("workgroup", "workgroup__proposal", "workgroup__proposal__proposed_by")
        .order_by("created_at")
    )
    return render(request, "cartels/review_queue.html", {
        "submitted": submitted,
        "can_approve": can_approve,
        "can_feedback": can_feedback,
    })


@login_required
@require_POST
def review_decide(request, pk):
    """The Program Committee registers (approve) or returns a submitted cartel
    for revision (decline)."""
    if not is_program_committee(request.user):
        raise Http404
    cartel = get_object_or_404(
        Cartel, pk=pk, registration_status=Cartel.RegistrationStatus.SUBMITTED
    )
    if request.POST.get("decision") == "approve":
        cartel.approve(request.user)
        notify_cartels.generator_decision(cartel, _abs(request, cartel))
        messages.success(request, f"Registered '{cartel.workgroup.name}'.")
    else:
        cartel.decline(request.user, note=request.POST.get("note", ""))
        notify_cartels.generator_decision(cartel, _abs(request, cartel))
        messages.success(request, f"Returned '{cartel.workgroup.name}' for revision.")
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
        notify_cartels.coordinator_feedback(cartel, _abs(request, cartel))
    messages.success(request, f"Feedback recorded for '{cartel.workgroup.name}'.")
    return redirect("cartels:review_queue")


@login_required
@require_POST
def apply(request, slug):
    """A member applies to join a forming/registered cartel (CART-4 step 5),
    with a note. Cartels are joinable from the moment they start forming
    (PC registration is a separate, later gate — see ``submit``)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    live = (Cartel.RegistrationStatus.FORMING, Cartel.RegistrationStatus.REGISTERED,
            Cartel.RegistrationStatus.SUBMITTED)
    if (cartel.registration_status not in live or cartel.workgroup.is_archived
            or not is_lsp_member(request.user) or cartel.closed
            or cartel.is_member(request.user)):
        raise Http404
    cartel.request_to_join(request.user, message=(request.POST.get("message") or "").strip())
    notify_cartels.members_of_application(cartel, request.user, _abs(request, cartel))
    messages.success(request, "Application sent — a member of the cartel will review it.")
    return redirect(cartel.get_absolute_url())


@login_required
def edit(request, slug):
    """Edit a cartel's details (name, theme, overview, invitees).

    A cartel is run collectively from the moment it starts forming, so any
    active member may edit its details — there's no separate proposal/review
    gate on the details themselves (PC review happens later, at submit)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    if request.method == "POST":
        form = CartelProposalForm(request.POST)
        if form.is_valid():
            wg = cartel.workgroup
            wg.name = form.cleaned_data["name"]
            wg.description = form.cleaned_data["description"]
            wg.save(update_fields=["name", "description"])
            cartel.theme = form.cleaned_data["theme"]
            cartel.save(update_fields=["theme"])
            for user in form.cleaned_data["invitees"]:
                cartel.invitations.get_or_create(
                    invited_user=user, defaults={"created_by": request.user}
                )
            messages.success(request, "Cartel details updated.")
            return redirect(f"{cartel.get_absolute_url()}?tab=settings")
        selected = _selected_invitees(form)
    else:
        form = CartelProposalForm(initial={
            "name": cartel.workgroup.name,
            "theme": cartel.theme,
            "description": cartel.workgroup.description,
        })
        selected = [
            inv.invited_user for inv in
            cartel.invitations.filter(accepted_at__isnull=True).select_related("invited_user")
        ]
    return render(request, "cartels/edit.html", {
        "cartel": cartel, "form": form, "selected_invitees": selected,
    })


@login_required
@require_POST
def manage(request, slug):
    """A member closes/reopens the cartel to new members, archives it, or
    reactivates (exhumes) an archived one.

    Reactivation has to work *after* archiving — which freezes active membership
    — so the gate accepts stored (roster) members and managers, not just active
    members."""
    from workgroups.permissions import can_manage_workgroup

    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    wg = cartel.workgroup
    is_stored = (
        request.user.is_authenticated
        and wg.memberships.serving().filter(user=request.user).exists()
    )
    if not (is_stored or can_manage_workgroup(request.user, wg)):
        raise Http404
    action = request.POST.get("action")
    if action == "close":
        cartel.set_closed(True)
    elif action == "reopen":
        cartel.set_closed(False)
    elif action == "archive":
        cartel.archive(by=request.user)
    elif action == "reactivate":
        cartel.unarchive(by=request.user)
    return redirect(f"{cartel.get_absolute_url()}?tab=settings")


def _settings_redirect(cartel):
    return redirect(f"{cartel.get_absolute_url()}?tab=settings")


@login_required
@require_POST
def set_plus_one(request, slug):
    """Designate an existing member as the (internal) plus-one — or, with no
    member selected, unset the current internal plus-one (demote to member)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    from accounts.models import User

    user_pk = request.POST.get("user")
    if not user_pk:
        cartel.clear_internal_plus_one()
        messages.success(request, "Internal plus-one removed.")
        return _settings_redirect(cartel)
    member = get_object_or_404(
        User, pk=user_pk,
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
        notify_cartels.external_plus_one(ext, signup_url)
        ext.invited_at = timezone.now()
        ext.save(update_fields=["invited_at"])
        messages.success(request, f"Invited {ext.name} to create an account.")
    else:
        messages.error(request, f"{ext.name} has no email on file.")
    return _settings_redirect(cartel)


@login_required
@require_POST
def remove_external_plus_one(request, slug, pk):
    """Remove an external (non-LSP) plus-one record."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
    if not cartel.is_member(request.user):
        raise Http404
    ext = get_object_or_404(ExternalPlusOne, pk=pk, cartel=cartel)
    name = ext.name
    ext.delete()
    messages.success(request, f"Removed external plus-one {name}.")
    return _settings_redirect(cartel)


@login_required
@require_POST
def accept_invitation(request, slug):
    """A seeded invitee accepts and joins directly (the invitation itself is
    the gate — no separate proposal-status check needed)."""
    cartel = get_object_or_404(Cartel, workgroup__slug=slug)
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
        CartelJoinRequest, pk=pk, workgroup=cartel.workgroup,
        status=CartelJoinRequest.Status.PENDING,
    )
    if request.POST.get("decision") == "accept":
        cartel.accept_request(join_request, decided_by=request.user)
    else:
        cartel.decline_request(join_request, decided_by=request.user)
    notify_cartels.applicant_decision(join_request, _abs(request, cartel))
    return redirect(cartel.get_absolute_url())
