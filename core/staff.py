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

#: Committee control panels: (committee slug, title, blurb, url name). A
#: committee member (or Django staff) sees its card. Board of Directors and
#: Meeting of Analysts slot in here once their admin surfaces are built.
COMMITTEE_PANELS = [
    ("programming-committee", "Program Committee",
     "Solicit and review proposals; mint events into a program.",
     "program_admin_programs"),
]


def _can_treasurer(user) -> bool:
    return user.is_superuser or user.is_staff or has_staff_role(user, StaffRole.TREASURER)


def _on_committee(user, slug: str) -> bool:
    from committees.permissions import is_on_committee
    return is_on_committee(user, slug)


def can_access_staff_tools(user) -> bool:
    """Entry gate to /staff/: true iff the user would see at least one tool —
    a panel-bearing staff role, Django staff, a superuser, or membership of a
    committee that has a panel. Kept cheap (no count queries) for the nav."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if has_staff_role(user, *PANEL_ROLES):
        return True
    return any(_on_committee(user, slug) for slug, *_ in COMMITTEE_PANELS)


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
    if is_cartel_coordinator(user):
        from cartels.models import Cartel
        panels.append({
            "title": "Cartel review",
            "blurb": "Review and approve proposed cartels.",
            "url": reverse("cartels:review_queue"),
            "count": Cartel.objects.filter(status=Cartel.Status.PROPOSED).count(),
            "count_label": "pending",
        })
    for slug, title, blurb, url_name in COMMITTEE_PANELS:
        if user.is_superuser or user.is_staff or _on_committee(user, slug):
            panels.append({"title": title, "blurb": blurb, "url": reverse(url_name)})
    if user.is_staff:
        panels.append({
            "title": "Django admin",
            "blurb": "The full back office for every model.",
            "url": "/admin/",
        })
    return panels


@login_required
def home(request):
    # Authoritative gate: you reach the hub iff you have at least one tool.
    panels = _panels_for(request.user)
    if not panels:
        raise PermissionDenied
    return render(request, "core/staff/home.html", {"panels": panels})


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
