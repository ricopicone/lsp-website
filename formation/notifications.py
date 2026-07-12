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


def external_analyst_requested(obj) -> None:
    """Notify the Meeting of the Analysts that a member requested an external
    control analyst."""
    from workgroups.permissions import meeting_of_analysts_members

    for reviewer in meeting_of_analysts_members():
        notify(
            reviewer, Category.EXTERNAL_CONTROL_ANALYST,
            title=f"{_name(obj.member)} requested an external control analyst",
            url=reverse("formation:external_analyst_queue"), target=obj, dedupe=True,
            email_fn=lambda r=reviewer: emails.send_external_analyst_requested(obj, r),
        )


def external_analyst_decision(obj) -> None:
    approved = obj.status == obj.Status.APPROVED
    notify(
        obj.member, Category.ADMISSIONS_DECISION,
        title=("Your external control analyst was approved" if approved
               else "Your external control analyst request was not approved"),
        url=reverse("formation:formation") + "?tab=formation#control", target=obj,
        email_fn=lambda: emails.send_external_analyst_decision(obj),
    )
