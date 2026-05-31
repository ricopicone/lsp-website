"""Cartels list — the public-facing index of cartels.

Each cartel's landing page is the shared Workspace surface
(``workgroups:detail``); this view is just the browsable directory.
"""

from __future__ import annotations

from django.shortcuts import render

from .models import Cartel


def index(request):
    cartels = [
        c for c in Cartel.objects.select_related("workgroup")
        if c.workgroup.landing_visible_to(request.user)
    ]
    return render(request, "cartels/index.html", {"cartels": cartels})
