"""Render Markdown-backed content pages."""

from __future__ import annotations

from django.http import Http404
from django.shortcuts import render

from committees.models import Committee

from . import loader


def about(request):
    """The /about/ page: Markdown body + dynamic board/committee rosters."""
    page = loader.load("about")
    if page is None:
        raise Http404("about page not found")
    committees = (
        Committee.objects
        .filter(public=True)
        .prefetch_related("memberships__user__profile")
        .order_by("name")
    )
    return render(request, "content/about.html", {
        "page": page,
        "committees": committees,
    })
