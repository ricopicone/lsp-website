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
    ``preview_profile_done`` reflects real data (a headshot *and* a bio), so the
    checklist auto-ticks when the member actually finishes rather than tracking
    clicks.
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

    profile = getattr(user, "profile", None)
    profile_done = bool(profile and profile.headshot and (profile.bio or "").strip())

    # "Register for the preview seminar" task — link + truthful completion. The
    # seminar is seeded by `manage.py seed_preview_seminar`; if it doesn't exist
    # yet, the checklist still renders the item (just without a link).
    from django.urls import reverse

    slug = getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", "")
    seminar_url = None
    register_done = False
    if slug:
        from events.models import Event
        from registrations.models import Registration

        event = Event.objects.filter(slug=slug).first()
        if event is not None:
            seminar_url = reverse("events:detail", args=[event.slug])
            register_done = (
                Registration.objects.filter(user=user, event=event)
                .exclude(status__in=(
                    Registration.Status.CANCELLED,
                    Registration.Status.REFUNDED,
                ))
                .exists()
            )

    # "Say hello in Parlêtre" task — link + truthful completion (has the member
    # posted in the welcome channel yet?).
    channel_slug = getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", "")
    channel_url = None
    channel_done = False
    if channel_slug:
        from parletre.models import Channel, Post

        channel = Channel.objects.filter(slug=channel_slug).first()
        if channel is not None:
            channel_url = reverse("parletre:channel", args=[channel.slug])
            channel_done = Post.objects.filter(author=user, channel=channel).exists()

    return {
        "show_preview_tour": True,
        "preview_profile_done": profile_done,
        "preview_register_done": register_done,
        "preview_seminar_url": seminar_url,
        "preview_seminar_slug": slug,
        "preview_channel_done": channel_done,
        "preview_channel_url": channel_url,
        "preview_channel_slug": channel_slug,
    }
