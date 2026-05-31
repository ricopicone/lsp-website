"""Views for the Workspace surface — the shared landing/detail page every
group kind renders through."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from works.models import Work

from .models import Workgroup

#: The Groups overview / dropdown order: kind, url-name suffix, label, blurb.
#: Drives both the overview cards and the per-kind routes in ``urls.py``.
KIND_META = [
    (Workgroup.Kind.SEMINAR, "seminars", "Seminars",
     "Year-long teaching seminars led by faculty."),
    (Workgroup.Kind.CARTEL, "cartels", "Cartels",
     "Small groups — several members and a “plus-one” — formed around a "
     "shared question."),
    (Workgroup.Kind.COMMITTEE, "committees", "Committees",
     "Standing committees that carry the work of the school."),
    (Workgroup.Kind.WORKING_GROUP, "working_groups", "Working Groups",
     "Task- and project-oriented groups organized around an aim."),
    (Workgroup.Kind.READING_GROUP, "reading_groups", "Reading Groups",
     "Groups reading a shared text or body of work together."),
]


def workgroup_list(request):
    """The Groups overview: one card per kind (always all of them)."""
    visible = [
        g for g in Workgroup.objects.all()
        if g.landing_visible_to(request.user)
    ]
    counts: dict[str, int] = {}
    for g in visible:
        counts[g.kind] = counts.get(g.kind, 0) + 1

    kinds = [
        {
            "label": label,
            "blurb": blurb,
            "url": reverse(f"workgroups:kind_{name}"),
            "count": counts.get(kind, 0),
        }
        for kind, name, label, blurb in KIND_META
    ]
    return render(request, "workgroups/list.html", {"kinds": kinds})


def workgroup_kind_list(request, kind):
    """The per-kind directory — visible workgroups of a single kind."""
    label = Workgroup.Kind(kind).label
    groups = [
        g for g in Workgroup.objects.filter(kind=kind)
        if g.landing_visible_to(request.user)
    ]
    return render(request, "workgroups/kind_list.html", {
        "kind_label": label,
        "kind_label_plural": f"{label}s",
        "groups": groups,
    })


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
