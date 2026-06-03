"""Admin Tools — one hub linking each governance body / staff role to its own
admin page.

``home`` lists the admin pages the current user can reach, one card each:
the **Board** and **Program Committee** (governance bodies), and the staff
roles (**Treasurer**, **Cartel Coordinator**, **Administrative Assistant**,
**Web Coordinator**, **Web Developer**). Each card is gated to its body/role,
so a user sees only their own. Some pages live here (web-coordinator,
web-developer, admin-assistant, board); others link to existing dashboards
(treasurer, program-committee, cartel review). Built to grow: gate a card in
``_panels_for`` by the relevant body/role.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .access import has_staff_role, staff_role_required
from .forms import AphorismForm
from .models import Aphorism, StaffRole

#: Staff roles that map to their own admin page in the hub (NB: lsp_staff has no
#: page of its own — it's a general designation, not an admin area).
PANEL_ROLES = (
    StaffRole.WEB_COORDINATOR,
    StaffRole.TREASURER,
    StaffRole.CARTEL_COORDINATOR,
    StaffRole.ADMIN_ASSISTANT,
    StaffRole.WEB_DEVELOPER,
)


def _can_treasurer(user) -> bool:
    return user.is_superuser or user.is_staff or has_staff_role(user, StaffRole.TREASURER)


def _can_board(user) -> bool:
    from committees.permissions import is_on_committee
    return user.is_superuser or user.is_staff or is_on_committee(user, "board")


def _can_program_committee(user) -> bool:
    from events.permissions import is_program_committee
    return user.is_superuser or user.is_staff or is_program_committee(user)


def _can_cartel_coordinator(user) -> bool:
    from cartels.permissions import is_cartel_coordinator
    return user.is_superuser or user.is_staff or is_cartel_coordinator(user)


def can_access_admin_tools(user) -> bool:
    """Entry gate to /admin-tools/: staff-role holders, Board members, and
    Program Committee members (plus Django staff / superusers). Members of
    *other* committees reach their workspace via Groups, not here. Kept cheap
    for the nav link."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if has_staff_role(user, *PANEL_ROLES):
        return True
    return _can_board(user) or _can_program_committee(user)


def _panels_for(user) -> list[dict]:
    """The admin pages ``user`` may reach, in display order. One card per
    governance body / staff role the user belongs to."""
    panels = []

    # --- Governance bodies ---
    if _can_board(user):
        panels.append({
            "title": "Board Admin",
            "blurb": "Board membership, documents, and meeting records.",
            "url": reverse("board_admin"),
        })
    if _can_program_committee(user):
        panels.append({
            "title": "Program Committee Admin",
            "blurb": "Solicit and review proposals; mint events into a program.",
            "url": reverse("program_admin_programs"),
        })

    # --- Staff roles ---
    if _can_treasurer(user):
        panels.append({
            "title": "Treasurer Admin",
            "blurb": "Dues and tuition dashboards, member ledgers, and exports.",
            "url": reverse("treasurer"),
        })
    if _can_cartel_coordinator(user):
        from cartels.models import Cartel
        panels.append({
            "title": "Cartel Coordinator Admin",
            "blurb": "Review proposed cartels (the PC approves; the Coordinator advises).",
            "url": reverse("cartels:review_queue"),
            "count": Cartel.objects.filter(
                workgroup__proposal__status=Cartel.Status.PROPOSED
            ).count(),
            "count_label": "pending",
        })
    if user.is_superuser or has_staff_role(user, StaffRole.ADMIN_ASSISTANT):
        panels.append({
            "title": "Administrative Assistant Admin",
            "blurb": "Board support: membership records, communications, scheduling.",
            "url": reverse("admin_assistant_admin"),
        })
    if user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR):
        panels.append({
            "title": "Web Coordinator Admin",
            "blurb": "Editable site content — aphorisms and more.",
            "url": reverse("web_coordinator_admin"),
        })
    if user.is_superuser or has_staff_role(user, StaffRole.WEB_DEVELOPER):
        panels.append({
            "title": "Web Developer Admin",
            "blurb": "Technical operations: the Django back office, deploys, internals.",
            "url": reverse("web_developer_admin"),
        })

    if user.is_staff:
        panels.append({
            "title": "Django admin",
            "blurb": "The full back office for every model.",
            "url": "/admin/",
        })
    return panels


#: Reference guides surfaced in the staff hub's Documentation section. Each is
#: a Markdown file under ``core/docs/`` rendered by :func:`core.docs.render_doc`.
STAFF_DOCS = [
    {
        "slug": "groups-guide",
        "title": "Groups — a guide",
        "blurb": (
            "How cartels, working groups, committees, seminars, reading groups, "
            "and the Meeting of Analysts work — who creates, approves, joins, "
            "runs, and ends each, with step-by-step recipes."
        ),
    },
]
_STAFF_DOCS_BY_SLUG = {d["slug"]: d for d in STAFF_DOCS}


@login_required
def home(request):
    # Authoritative gate: you reach the hub iff you have at least one tool.
    panels = _panels_for(request.user)
    if not panels:
        raise PermissionDenied
    docs = [
        {**d, "url": reverse("staff_doc", args=[d["slug"]])} for d in STAFF_DOCS
    ]
    return render(request, "core/staff/home.html", {"panels": panels, "docs": docs})


@login_required
def doc(request, slug):
    """Render a staff documentation guide (Documentation section of the hub)."""
    if not _panels_for(request.user):
        raise PermissionDenied
    meta = _STAFF_DOCS_BY_SLUG.get(slug)
    if meta is None:
        raise Http404
    from core.docs import render_doc

    return render(request, "core/staff/doc.html", {
        "title": meta["title"],
        "rendered_html": render_doc(slug),
    })


# ---- Per-body / per-role admin landing pages --------------------------------


@login_required
def board_admin(request):
    """Board's admin landing. Gated to Board members (+ staff/superuser).

    School-governance actions only — the Board's own roster, documents, minutes,
    decisions, and discussion live in its workspace, linked from the page.
    """
    if not _can_board(request.user):
        raise PermissionDenied
    from committees.models import Committee
    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    workspace_url = (
        reverse("workgroups:detail", args=[board.workgroup.slug])
        if board and board.workgroup_id
        else None
    )
    return render(request, "core/staff/admin/board.html", {
        "workspace_url": workspace_url,
    })


@login_required
def board_membership_admin(request):
    """Membership administration (Board record-keeping): admit members and record
    role/standing transitions, writing each member's tenure timeline + the live
    Profile. Gated to Board members (+ staff/superuser)."""
    if not _can_board(request.user):
        raise PermissionDenied
    from django.contrib import messages
    from django.db.models import Q

    from accounts.forms import MembershipChangeForm
    from accounts.membership import (
        current_academic_year_start,
        record_membership_change,
    )
    from accounts.models import MembershipTenure, User

    member = None
    form = None
    if request.method == "POST":
        member = get_object_or_404(User, pk=request.POST.get("member"))
        form = MembershipChangeForm(request.POST)
        if form.is_valid():
            record_membership_change(
                member,
                role=form.cleaned_data["role"],
                standing=form.cleaned_data["standing"],
                effective_ay=form.cleaned_data["effective_ay"],
                notes=form.cleaned_data["notes"],
                by=request.user,
            )
            messages.success(
                request,
                f"Recorded a membership change for "
                f"{member.get_full_name() or member.email}.",
            )
            return redirect(f"{reverse('board_membership_admin')}?member={member.pk}")
    else:
        member_id = request.GET.get("member")
        if member_id:
            member = (
                User.objects.filter(pk=member_id).select_related("profile").first()
            )

    q = (request.GET.get("q") or "").strip()
    results = []
    if q and member is None:
        results = list(
            User.objects.filter(
                Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q),
            )
            .select_related("profile")
            .order_by("last_name", "first_name", "email")[:50]
        )

    timeline = []
    if member is not None:
        timeline = list(
            MembershipTenure.objects.filter(user=member).order_by("-start_ay")
        )
        if form is None:
            form = MembershipChangeForm(initial={
                "role": member.profile.role,
                "standing": member.profile.standing,
                "effective_ay": current_academic_year_start(),
            })

    return render(request, "core/staff/admin/board_membership.html", {
        "q": q, "results": results, "member": member,
        "timeline": timeline, "form": form,
    })


@login_required
@staff_role_required(StaffRole.ADMIN_ASSISTANT)
def admin_assistant_admin(request):
    """Administrative Assistant to the Board admin landing."""
    return render(request, "core/staff/admin/admin_assistant.html", {})


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def web_coordinator_admin(request):
    """Web Coordinator admin landing — site content tools (aphorisms + more)."""
    return render(request, "core/staff/admin/web_coordinator.html", {
        "active_aphorisms": Aphorism.objects.filter(is_active=True).count(),
        "total_aphorisms": Aphorism.objects.count(),
    })


@login_required
@staff_role_required(StaffRole.WEB_DEVELOPER)
def web_developer_admin(request):
    """Web Developer admin landing — technical operations."""
    return render(request, "core/staff/admin/web_developer.html", {})


# ---- Aphorisms panel --------------------------------------------------------


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_list(request):
    return render(
        request,
        "core/staff/aphorisms.html",
        {"aphorisms": Aphorism.objects.all()},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_create(request):
    form = AphorismForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism added.")
        return redirect("staff_aphorisms")
    return render(request, "core/staff/aphorism_form.html", {"form": form, "mode": "new"})


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_edit(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    form = AphorismForm(request.POST or None, instance=aphorism)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism updated.")
        return redirect("staff_aphorisms")
    return render(
        request,
        "core/staff/aphorism_form.html",
        {"form": form, "mode": "edit", "aphorism": aphorism},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_delete(request, pk):
    get_object_or_404(Aphorism, pk=pk).delete()
    messages.success(request, "Aphorism deleted.")
    return redirect("staff_aphorisms")


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_toggle(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    aphorism.is_active = not aphorism.is_active
    aphorism.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Aphorism {'shown' if aphorism.is_active else 'hidden'}.")
    return redirect("staff_aphorisms")
