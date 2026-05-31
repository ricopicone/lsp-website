"""Web Coordinator control panel — a hub of staff-role-gated tools.

The hub lists the panels the current user can reach (by ``core.StaffRole``).
First panel: aphorism management. Built to grow — add a panel, gate it with a
role key, and list it in ``_panels_for``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .access import coordinator_required, has_staff_role, staff_role_required
from .forms import AphorismForm
from .models import Aphorism, StaffRole


def _panels_for(user) -> list[dict]:
    """The control panels ``user`` may access, in display order."""
    panels = []
    if has_staff_role(user, StaffRole.WEB_COORDINATOR):
        panels.append(
            {
                "title": "Aphorisms",
                "blurb": "Edit the Lacanian aphorisms that rotate in the footer.",
                "url": reverse("coordinator_aphorisms"),
                "count": Aphorism.objects.filter(is_active=True).count(),
                "count_label": "active",
            }
        )
    return panels


@login_required
@coordinator_required
def home(request):
    return render(
        request,
        "core/coordinator/home.html",
        {"panels": _panels_for(request.user)},
    )


# ---- Aphorisms panel --------------------------------------------------------


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_list(request):
    aphorisms = Aphorism.objects.all()
    return render(
        request,
        "core/coordinator/aphorisms.html",
        {"aphorisms": aphorisms},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_create(request):
    form = AphorismForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism added.")
        return redirect("coordinator_aphorisms")
    return render(
        request,
        "core/coordinator/aphorism_form.html",
        {"form": form, "mode": "new"},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_edit(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    form = AphorismForm(request.POST or None, instance=aphorism)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism updated.")
        return redirect("coordinator_aphorisms")
    return render(
        request,
        "core/coordinator/aphorism_form.html",
        {"form": form, "mode": "edit", "aphorism": aphorism},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_delete(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    aphorism.delete()
    messages.success(request, "Aphorism deleted.")
    return redirect("coordinator_aphorisms")


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_toggle(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    aphorism.is_active = not aphorism.is_active
    aphorism.save(update_fields=["is_active", "updated_at"])
    messages.success(
        request,
        f"Aphorism {'shown' if aphorism.is_active else 'hidden'}.",
    )
    return redirect("coordinator_aphorisms")
