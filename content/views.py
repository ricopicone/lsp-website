"""Render Markdown-backed content pages."""

from __future__ import annotations

import re

from django.http import Http404
from django.shortcuts import render
from django.template.loader import render_to_string

from committees.models import Committee

from . import guides as guides_index
from . import loader
from . import the_school as the_school_index

ROSTER_PLACEHOLDER_RE = re.compile(r"<!--\s*ROSTER:([\w-]+)\s*-->")


def about(request):
    """The /about/ page: Markdown body with inline roster cards."""
    page = loader.load("about")
    if page is None:
        raise Http404("about page not found")

    committees_by_slug = {
        c.slug: c
        for c in Committee.objects.filter(public=True)
                                  .select_related("workgroup")
                                  .prefetch_related("workgroup__memberships__user__profile")
    }

    def _replace(match):
        committee = committees_by_slug.get(match.group(1))
        if committee is None:
            return ""
        return render_to_string("content/_roster.html", {"committee": committee})

    body_html = ROSTER_PLACEHOLDER_RE.sub(_replace, page.body_html)

    return render(request, "content/about.html", {
        "page": page,
        "body_html": body_html,
    })


def the_school(request):
    """The School: a graphical index — visual table of contents over the
    School's concepts and bodies, with an encyclopedia-style entry per block.

    The graphic and the entries are both built from one taxonomy, so they can
    never disagree. See ``content/the_school.py``.
    """
    return render(request, "content/the_school.html", {
        "rows": the_school_index.build_rows(),
    })


def guides_index_view(request):
    """The Guides index: a card grid of evergreen how-to pages, plus a
    role-gated "Your staff guides" section linking to in-tool staff help."""
    from . import staff_guides

    return render(request, "content/guides_index.html", {
        "guides": guides_index.all_guides(),
        "staff_guides": staff_guides.for_user(request.user),
    })


def guide_detail(request, slug):
    """One guide page: rendered Markdown plus an optional "Start this
    walkthrough" button that activates the guide's tailored checklist in the
    floating card and lands the member on its first step."""
    guide = guides_index.get_guide(slug)
    if guide is None:
        raise Http404("guide not found")

    start_url = None
    walkthrough_title = ""
    if guide.checklist:
        from urllib.parse import urlencode

        from django.urls import reverse

        from core.checklists import first_step_url, get_checklist

        checklist = get_checklist(guide.checklist)
        if checklist is not None:
            walkthrough_title = checklist.title
            nxt = first_step_url(guide.checklist, request) or request.path
            start_url = reverse("core:set_walkthrough") + "?" + urlencode(
                {"id": guide.checklist, "next": nxt}
            )

    return render(request, "content/guide_detail.html", {
        "guide": guide,
        "start_url": start_url,
        "walkthrough_title": walkthrough_title,
    })
