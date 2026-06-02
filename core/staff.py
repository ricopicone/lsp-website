"""Staff tools — one hub for every staff-role-gated control panel.

``home`` lists the tools the current user can reach (by ``core.StaffRole``,
plus Django staff for the financial tools). Some tools live here (aphorisms);
others are links to existing dashboards (treasurer, cartel review). Built to
grow: gate a card in ``_panels_for`` by the relevant role.
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

#: Roles that map to a tool in the hub (NB: lsp_staff has no panel of its own).
PANEL_ROLES = (
    StaffRole.WEB_COORDINATOR,
    StaffRole.TREASURER,
    StaffRole.CARTEL_COORDINATOR,
)

#: Committees with a bespoke admin tool. Every other committee's card links to
#: its workgroup page (where its roster, minutes, decisions, and discussion
#: live). Add a bespoke admin here only when one exists.
COMMITTEE_ADMIN_URLS = {"programming-committee": "program_admin_programs"}

_COMMITTEE_BLURBS = {
    "programming-committee": "Solicit and review proposals; mint events into a program.",
}
_DEFAULT_COMMITTEE_BLURB = "Roster, minutes, decisions, and discussion."


def _can_treasurer(user) -> bool:
    return user.is_superuser or user.is_staff or has_staff_role(user, StaffRole.TREASURER)


def _member_committee_slugs(user) -> set[str]:
    """Slugs of committees the user is a current member of."""
    from workgroups.models import WorkgroupMembership

    return set(
        WorkgroupMembership.objects.filter(
            user=user, end_date__isnull=True, workgroup__committee__isnull=False,
        ).values_list("workgroup__committee__slug", flat=True)
    )


def can_access_staff_tools(user) -> bool:
    """Entry gate to /staff/: true iff the user would see at least one tool —
    a panel-bearing staff role, Django staff, a superuser, or membership of any
    committee. Kept cheap (no count queries) for the nav link."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if has_staff_role(user, *PANEL_ROLES):
        return True
    return bool(_member_committee_slugs(user))


def _panels_for(user) -> list[dict]:
    """The staff tools ``user`` may reach, in display order."""
    panels = []
    if user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR):
        panels.append({
            "title": "Aphorisms",
            "blurb": "Edit the Lacanian aphorisms that rotate in the footer.",
            "url": reverse("staff_aphorisms"),
            "count": Aphorism.objects.filter(is_active=True).count(),
            "count_label": "active",
        })
    if _can_treasurer(user):
        panels.append({
            "title": "Treasurer",
            "blurb": "Dues and tuition dashboards, member ledgers, and exports.",
            "url": reverse("treasurer"),
        })
    from cartels.permissions import is_cartel_coordinator
    from events.permissions import is_program_committee
    if is_cartel_coordinator(user) or is_program_committee(user):
        from cartels.models import Cartel
        panels.append({
            "title": "Cartel review",
            "blurb": "Review proposed cartels (the PC approves; the Coordinator advises).",
            "url": reverse("cartels:review_queue"),
            "count": Cartel.objects.filter(
                workgroup__proposal__status=Cartel.Status.PROPOSED
            ).count(),
            "count_label": "pending",
        })
    # One card per committee the user can reach (member, or staff/superuser).
    from committees.models import Committee

    member_slugs = _member_committee_slugs(user)
    sees_all = user.is_superuser or user.is_staff
    for c in Committee.objects.select_related("workgroup").order_by("name"):
        if not (sees_all or c.slug in member_slugs):
            continue
        if c.slug in COMMITTEE_ADMIN_URLS:
            url = reverse(COMMITTEE_ADMIN_URLS[c.slug])
        elif c.workgroup_id:
            url = reverse("workgroups:detail", args=[c.workgroup.slug])
        else:
            continue
        panels.append({
            "title": c.name,
            "blurb": _COMMITTEE_BLURBS.get(c.slug, _DEFAULT_COMMITTEE_BLURB),
            "url": url,
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
