"""Data-driven onboarding checklists.

A :class:`ChecklistTask` is one step: a label, a link, a completion check
against real data, and an optional contextual hint (a pulsing anchor + popover
on the relevant page). A checklist is an ordered list of tasks. The preview
tour is the first checklist; adding another feature walkthrough is a task entry
here plus a page that carries the hint anchor — no template surgery.

``core.context_processors.preview_tour`` resolves each task for the current
user into a plain dict the templates render (the floating checklist in
``base.html`` and the reusable ``core/_tour_hint.html`` include).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class ChecklistTask:
    id: str
    label: str
    detail: str
    resolve_url: Callable[[object], str | None]  # (request) -> url or None
    is_done: Callable[[object, object], bool]     # (user, request) -> bool
    # Optional contextual hint shown (until the task is done) on the page that
    # carries ``hint_selector``.
    hint_selector: str = ""
    hint_text: str = ""               # may contain trusted inline HTML
    hint_placement: str = "below"     # "below" | "above"
    hint_key: str = ""                # localStorage dismissal key

    def key(self) -> str:
        return self.hint_key or f"lsp-tour-{self.id}-hint"

    def resolved(self, user, request) -> dict:
        """Flatten to a template-ready dict for the current user."""
        try:
            url = self.resolve_url(request)
        except NoReverseMatch:
            url = None
        done = bool(self.is_done(user, request))
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "url": url,
            "done": done,
            "hint_selector": self.hint_selector,
            "hint_text": self.hint_text,
            "hint_placement": self.hint_placement,
            "hint_key": self.key(),
            # The hint shows until the task is done (and only where it has an
            # anchor). Page-specific gating — "is this the right page" — stays
            # in the page template around the include.
            "show_hint": (not done) and bool(self.hint_selector),
        }


# --- Completion checks + link resolvers for the preview tour ---------------

def _profile_url(request):
    return reverse("profile_edit")


def _profile_done(user, request):
    p = getattr(user, "profile", None)
    return bool(p and p.headshot and (p.bio or "").strip())


def _preview_event():
    from events.models import Event

    slug = getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", "")
    return Event.objects.filter(slug=slug).first() if slug else None


def _register_url(request):
    event = _preview_event()
    return reverse("events:detail", args=[event.slug]) if event else None


def _register_done(user, request):
    from registrations.models import Registration

    event = _preview_event()
    if event is None:
        return False
    return (
        Registration.objects.filter(user=user, event=event)
        .exclude(status__in=(
            Registration.Status.CANCELLED,
            Registration.Status.REFUNDED,
        ))
        .exists()
    )


def _preview_channel():
    from parletre.models import Channel

    slug = getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", "")
    return Channel.objects.filter(slug=slug).first() if slug else None


def _channel_url(request):
    channel = _preview_channel()
    return reverse("parletre:channel", args=[channel.slug]) if channel else None


def _channel_done(user, request):
    from parletre.models import Post

    channel = _preview_channel()
    if channel is None:
        return False
    return Post.objects.filter(author=user, channel=channel).exists()


PREVIEW_CHECKLIST_ID = "preview"


def _preview_checklist() -> list[ChecklistTask]:
    return [
        ChecklistTask(
            id="complete_profile",
            label="Complete your profile",
            detail="Add a photo and a short bio.",
            resolve_url=_profile_url,
            is_done=_profile_done,
            hint_selector="#choose-photo",
            hint_text=(
                "<strong>Start here.</strong> Add your photo and a short bio — "
                "they appear across the site."
            ),
            hint_placement="below",
            hint_key="lsp-preview-tour-photo-hint",
        ),
        ChecklistTask(
            id="register_seminar",
            label="Register for the preview seminar",
            detail="It's free and instant — try the sign-up flow.",
            resolve_url=_register_url,
            is_done=_register_done,
            hint_selector="#register-cta",
            hint_text=(
                "<strong>Try it.</strong> This sandbox seminar is free — register "
                "to see the whole sign-up flow. You can cancel afterward."
            ),
            hint_placement="below",
            hint_key="lsp-preview-tour-register-hint",
        ),
        ChecklistTask(
            id="say_hello",
            label="Say hello in Parlêtre",
            detail="Post a hello in the welcome channel.",
            resolve_url=_channel_url,
            is_done=_channel_done,
            hint_selector=".parletre-composer",
            hint_text=(
                "<strong>Say hi 👋</strong> Type a quick hello here and press "
                "Enter — the others in the preview will see it."
            ),
            hint_placement="above",
            hint_key="lsp-preview-tour-hello-hint",
        ),
    ]


# Registry of named checklists. A factory (not a list) so URLs/checks resolve
# at request time, not import time.
CHECKLISTS: dict[str, Callable[[], list[ChecklistTask]]] = {
    PREVIEW_CHECKLIST_ID: _preview_checklist,
}


def get_checklist(checklist_id: str) -> list[ChecklistTask]:
    factory = CHECKLISTS.get(checklist_id)
    return factory() if factory else []


def find_task(checklist_id: str, task_id: str) -> ChecklistTask | None:
    for task in get_checklist(checklist_id):
        if task.id == task_id:
            return task
    return None
