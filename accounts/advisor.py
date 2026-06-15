"""Advisorship — who may advise whom, and recording an advisor choice.

Per the formation guidelines: an analyst-track in-training member's Advisor must
be an Analyst of the School; a scholar-track member's Advisor may be a Scholar or
an Analyst of the School. The advisee chooses; the Board may also set it on their
behalf. ``set_advisor`` is the chokepoint — it closes any prior advisorship and
opens a new one, and notifies the advisor.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import Advisorship, Profile, User


def advisor_roles_for(advisee_role: str) -> set[str]:
    """The roles eligible to advise a member with ``advisee_role``."""
    if advisee_role in Profile.SCHOLAR_TRACK_ROLES:
        return {Profile.Role.SCHOLAR, Profile.Role.ANALYST}
    return {Profile.Role.ANALYST}


def eligible_advisors(advisee):
    """Active members whose role may advise ``advisee``, excluding the advisee."""
    return (
        User.objects.filter(
            is_active=True,
            profile__is_persona=False,
            profile__standing=Profile.Standing.ACTIVE,
            profile__role__in=advisor_roles_for(advisee.profile.role),
        )
        .exclude(pk=advisee.pk)
        .select_related("profile")
        .order_by("last_name", "first_name", "email")
    )


def current_advisor(advisee):
    a = (
        Advisorship.objects.filter(advisee=advisee, end_date__isnull=True)
        .select_related("advisor")
        .first()
    )
    return a.advisor if a else None


@transaction.atomic
def set_advisor(advisee, advisor, *, by=None, note=""):
    """Record ``advisor`` as ``advisee``'s current advisor (idempotent if it's
    already them). Closes any prior advisorship and notifies the new advisor."""
    Advisorship.objects.filter(advisee=advisee, end_date__isnull=True).exclude(
        advisor=advisor
    ).update(end_date=timezone.localdate())
    advisorship, created = Advisorship.objects.get_or_create(
        advisee=advisee, advisor=advisor, end_date__isnull=True,
        defaults={"note": note},
    )
    if created:
        _notify_advisor(advisorship)
    return advisorship


def _notify_advisor(advisorship: Advisorship) -> None:
    """In-app bell + (preference-gated) email to the chosen advisor."""
    from notifications.categories import Category
    from notifications.dispatch import notify

    advisee = advisorship.advisee
    name = advisee.get_full_name() or advisee.email
    notify(
        advisorship.advisor, Category.ACCOUNT_ADVISOR,
        title=f"{name} chose you as their Advisor",
        url="/directory/", target=advisorship,
        email_fn=lambda: _notify(advisorship),
    )


def _notify(advisorship: Advisorship) -> None:
    import logging

    from core.email import school_from
    try:
        advisee = advisorship.advisee
        name = advisee.get_full_name() or advisee.email
        EmailMessage(
            subject="You've been chosen as an Advisor at LSP",
            body=(
                f"Dear {advisorship.advisor.get_full_name() or advisorship.advisor.email},\n\n"
                f"{name} has chosen you as their Advisor in their LSP formation. "
                "They may reach out to discuss their theoretical training and the "
                "steps of their formation.\n\n"
                "— The Lacanian School of Psychoanalysis"
            ),
            from_email=school_from("LSP Formation"),
            to=[advisorship.advisor.email],
            reply_to=[settings.SUPPORT_EMAIL],
        ).send(fail_silently=False)
    except Exception:
        logging.getLogger(__name__).exception(
            "advisor-assigned email failed for %s", advisorship.pk
        )
