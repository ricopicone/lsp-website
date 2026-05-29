"""Render Markdown-backed content pages."""

from __future__ import annotations

import re

from django.http import Http404
from django.shortcuts import render
from django.template.loader import render_to_string

from committees.models import Committee

from . import loader

ROSTER_PLACEHOLDER_RE = re.compile(r"<!--\s*ROSTER:([\w-]+)\s*-->")


def about(request):
    """The /about/ page: Markdown body with inline roster cards."""
    page = loader.load("about")
    if page is None:
        raise Http404("about page not found")

    committees_by_slug = {
        c.slug: c
        for c in Committee.objects.filter(public=True)
                                  .prefetch_related("memberships__user__profile")
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
