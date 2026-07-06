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


SITE_THEMES = ("modern", "wix")
SITE_THEME_COOKIE = "lsp-site-theme"
# Default skin for visitors with no cookie set. The Board's website review
# (task #349) chose the Classic look — the ``wix`` artwork/serif/silk skin from
# task #259 — as the site's default; ``modern`` remains available via the footer
# switch.
DEFAULT_SITE_THEME = "wix"


def site_theme(request):
    """The active site-theme skin: ``wix`` (Classic — the artwork/serif/all-caps
    look from task #259, now the default) or ``modern`` (the opt-out plain skin).
    Read from a cookie set by ``core:set_site_theme``; rendered onto
    ``<html data-site-theme>`` and used by the hero partial to decide between an
    artwork band and a plain header."""
    value = request.COOKIES.get(SITE_THEME_COOKIE, DEFAULT_SITE_THEME)
    if value not in SITE_THEMES:
        value = DEFAULT_SITE_THEME
    return {"site_theme": value}


def page_artwork(request):
    """Artwork for the current page's section-landing hero, if any.

    Resolved from the static map in ``core.page_artwork`` keyed by the
    namespaced view name. Section-landing templates override the base
    ``page_hero`` block and the partial reads this; unmapped pages get an
    image-less header.
    """
    from . import page_artwork as artwork_map

    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match is not None else None
    return {"page_artwork": artwork_map.for_view(view_name)}


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
        return {"show_preview_tour": False, "walkthroughs_enabled": False}

    # Public → everyone signed in. Otherwise gate on the allowlist (empty list
    # also means everyone). Empty strings are filtered so `ALLOWLIST=` reads as
    # "no restriction" rather than a one-element [""] that excludes all.
    public = getattr(settings, "PREVIEW_TOUR_PUBLIC", False)
    allowlist = [a.lower() for a in getattr(settings, "PREVIEW_TOUR_ALLOWLIST", []) if a.strip()]
    if not public and allowlist and (user.email or "").lower() not in allowlist:
        return {"show_preview_tour": False, "walkthroughs_enabled": False}

    # Walkthroughs are available to this viewer (the Start buttons show), but the
    # floating card appears only once one is *active* (started from a guide) —
    # there's no always-on card.
    from core.checklists import active_checklist

    checklist = active_checklist(request)
    if checklist is None:
        return {"show_preview_tour": False, "walkthroughs_enabled": True}

    tasks = [t.resolved(user, request) for t in checklist.tasks]
    return {
        "show_preview_tour": True,
        "walkthroughs_enabled": True,
        "walkthrough_id": checklist.id,
        "walkthrough_title": checklist.title,
        "preview_tour_tasks": tasks,
        "preview_tour_tasks_by_id": {t["id"]: t for t in tasks},
        "preview_seminar_slug": getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", ""),
        "preview_channel_slug": getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", ""),
    }
