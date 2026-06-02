"""Working-group views — Board-gated creation (G3).

Roster management, leave, and archive are inherited generically from the
Workgroup layer (the Workspace surface at ``/groups/<slug>/``); this app only
owns the creation entry point.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from workgroups.permissions import is_board

from .forms import WorkingGroupCreateForm
from .models import WorkingGroup


def _can_create(user) -> bool:
    return bool(getattr(user, "is_staff", False)) or is_board(user)


@login_required
def create(request):
    """The Board (or staff) charters a working group, naming its chair and any
    initial members."""
    if not _can_create(request.user):
        raise Http404
    if request.method == "POST":
        form = WorkingGroupCreateForm(request.POST)
        if form.is_valid():
            wg = WorkingGroup.objects.create_with_chair(
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                chair=form.cleaned_data["chair"],
                members=form.cleaned_data["members"],
            )
            messages.success(request, f"Created working group '{wg.workgroup.name}'.")
            return redirect(wg.get_absolute_url())
    else:
        form = WorkingGroupCreateForm()
    return render(request, "workinggroups/create.html", {"form": form})
