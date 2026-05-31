"""Views for the Workspace surface — the shared landing/detail page every
group kind renders through."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from works.models import Work

from .models import Workgroup


def workgroup_list(request):
    """All workgroups whose landing page is visible to the user, by kind."""
    groups = [
        g for g in Workgroup.objects.all()
        if g.landing_visible_to(request.user)
    ]
    return render(request, "workgroups/list.html", {"groups": groups})


def workgroup_detail(request, slug):
    """The Workspace — about / roster / works, gated by visibility."""
    wg = get_object_or_404(Workgroup, slug=slug)
    if not wg.landing_visible_to(request.user):
        raise Http404  # don't reveal that a hidden group exists

    can_view = wg.content_visible_to(request.user)
    is_member = wg.is_member(request.user)
    members = list(wg.active_members()) if can_view else []
    works = []
    if can_view and wg.has_works:
        works = list(
            Work.listing_for(request.user)
            .filter(workgroup=wg)
            .prefetch_related("files")
        )
    # Link to the group's discussion channel for members (Parlêtre, Stage 2).
    channel = wg.channels.first() if is_member else None
    return render(request, "workgroups/detail.html", {
        "workgroup": wg,
        "can_view_content": can_view,
        "members": members,
        "works": works,
        "is_member": is_member,
        "channel": channel,
    })
