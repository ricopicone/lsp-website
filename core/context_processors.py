"""Template context processors for the ``core`` app."""

from __future__ import annotations

import random

from django.core.cache import cache

from .models import APHORISM_CACHE_KEY


def _active_aphorisms() -> list[dict]:
    """The active aphorisms as plain dicts, cached (invalidated on edit).

    The footer renders on every page, so we cache the small active list and
    pick in Python rather than issuing an ``ORDER BY RANDOM`` per request. The
    cache is dropped whenever an Aphorism is saved or deleted (see
    ``core.models``); the TTL is a backstop for multi-process caches.
    """
    items = cache.get(APHORISM_CACHE_KEY)
    if items is None:
        from .models import Aphorism

        items = list(
            Aphorism.objects.filter(is_active=True).values(
                "quote", "short_attribution", "full_attribution"
            )
        )
        cache.set(APHORISM_CACHE_KEY, items, 300)
    return items


def aphorism(request):
    """One Lacanian aphorism per page render. Surfaces in the footer."""
    items = _active_aphorisms()
    return {"aphorism": random.choice(items) if items else None}


def survey_nudge(request):
    """Whether to show the launch intake-survey banner: enabled, the user is an
    authenticated member, and they haven't submitted yet. Cheap — one indexed
    OneToOne lookup, only for logged-in users when the survey is live."""
    from django.conf import settings

    user = getattr(request, "user", None)
    if not (getattr(settings, "SURVEY_ENABLED", False)
            and user is not None and user.is_authenticated):
        return {"show_survey_nudge": False}
    submitted = (
        getattr(getattr(user, "intake_survey", None), "submitted_at", None) is not None
    )
    return {"show_survey_nudge": not submitted}


def preview_tour(request):
    """Limited-preview onboarding tour gating + task state.

    Shows the floating task checklist (and the per-page hints) only when the
    tour is enabled and the signed-in user is in the preview cohort. The cohort
    is every authenticated user when ``PREVIEW_TOUR_PUBLIC`` is on (or the
    allowlist is empty), otherwise just the allowlisted addresses.

    The tasks themselves are defined in ``core.checklists`` (the ``preview``
    checklist). Each is resolved against real data here, so the checklist
    auto-ticks when the member actually finishes rather than tracking clicks.
    ``preview_tour_tasks_by_id`` lets a feature page pull its own task for the
    reusable ``core/_tour_hint.html`` include. ``preview_seminar_slug`` /
    ``preview_channel_slug`` remain for the page-specific "is this the right
    page" gating around those hints.
    """
    from django.conf import settings

    user = getattr(request, "user", None)
    if not (getattr(settings, "PREVIEW_TOUR_ENABLED", False)
            and user is not None and user.is_authenticated):
        return {"show_preview_tour": False}

    # Public → everyone signed in. Otherwise gate on the allowlist (empty list
    # also means everyone). Empty strings are filtered so `ALLOWLIST=` reads as
    # "no restriction" rather than a one-element [""] that excludes all.
    public = getattr(settings, "PREVIEW_TOUR_PUBLIC", False)
    allowlist = [a.lower() for a in getattr(settings, "PREVIEW_TOUR_ALLOWLIST", []) if a.strip()]
    if not public and allowlist and (user.email or "").lower() not in allowlist:
        return {"show_preview_tour": False}

    from core.checklists import PREVIEW_CHECKLIST_ID, get_checklist

    tasks = [t.resolved(user, request) for t in get_checklist(PREVIEW_CHECKLIST_ID)]
    return {
        "show_preview_tour": True,
        "preview_tour_tasks": tasks,
        "preview_tour_tasks_by_id": {t["id"]: t for t in tasks},
        "preview_seminar_slug": getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", ""),
        "preview_channel_slug": getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", ""),
    }
