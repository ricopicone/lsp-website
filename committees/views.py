"""Committee views — the member-facing manage surface (charter editing).

Roster management, scheduling, and archive are inherited generically from the
Workgroup layer (the Workspace settings tab); committees add only charter edit.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from workgroups.permissions import can_manage_workgroup

from .forms import CommitteeCharterForm
from .models import Committee


@login_required
@require_POST
def edit_charter(request, slug):
    """A manager (committee lead, LSP staff, PC, or Board) edits the committee's
    summary + charter. ``slug`` is the backing workgroup's slug."""
    committee = get_object_or_404(Committee, workgroup__slug=slug)
    wg = committee.workgroup
    if not can_manage_workgroup(request.user, wg):
        raise Http404
    form = CommitteeCharterForm(request.POST, instance=committee)
    if form.is_valid():
        form.save()
        messages.success(request, "Charter updated.")
    return redirect(f"{wg.get_absolute_url()}?tab=settings")
