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
