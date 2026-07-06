"""Notification wrappers for the ongoing-formation (advancement demande)
pipeline.

Each adds an in-app bell row and, when the member's preference allows, sends
the existing formation email (passed as ``email_fn``). Call these instead of
``formation.emails`` directly.

The application (intake) notifications stay in ``admissions.notifications``.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails


def _name(user) -> str:
    return (user.get_full_name() if user else "") or "A member"


def advancement_opened(advancement) -> None:
    advisor = advancement.advisor
    if advisor is None:
        return
    notify(
        advisor, Category.ADMISSIONS_ADVANCEMENT,
        title=f"{_name(advancement.member)} opened a demande for your presentation",
        url=reverse("formation:advise_queue"), target=advancement,
        email_fn=lambda: emails.send_advancement_opened(advancement),
    )


def advancement_reminder(advancement) -> None:
    advisor = advancement.advisor
    if advisor is None:
        return
    notify(
        advisor, Category.ADMISSIONS_ADVANCEMENT,
        title=f"Reminder: present {_name(advancement.member)}'s demande",
        url=reverse("formation:advise_queue"), target=advancement, dedupe=True,
        email_fn=lambda: emails.send_advancement_reminder(advancement),
    )


def advancement_presented(advancement) -> None:
    notify(
        advancement.member, Category.ADMISSIONS_ADVANCEMENT,
        title="Your demande has been presented",
        url=reverse("formation:formation"), target=advancement,
        email_fn=lambda: emails.send_advancement_presented(advancement),
    )


def advancement_decision(advancement) -> None:
    notify(
        advancement.member, Category.ADMISSIONS_DECISION,
        title="A decision on your advancement",
        url=reverse("formation:formation"), target=advancement,
        email_fn=lambda: emails.send_advancement_decision(advancement),
    )
