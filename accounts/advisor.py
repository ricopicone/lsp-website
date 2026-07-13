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
    """Active members whose role may advise ``advisee``, excluding the advisee.

    Analysts who declared they are *not* available as an Advisor (an open
    availability span with status "no" for the ``advisor`` function) are
    dropped. "Yes" and "Unknown" (never reported) both stay eligible, so an
    analyst who simply hasn't filled the availability sheet isn't hidden. Only
    Analysts of the School carry availability spans, so scholar-track advisors
    are unaffected.
    """
    return (
        User.objects.filter(
            is_active=True,
            profile__is_persona=False,
            profile__standing=Profile.Standing.ACTIVE,
            profile__role__in=advisor_roles_for(advisee.profile.role),
        )
        .exclude(pk=advisee.pk)
        .exclude(
            profile__availability_spans__function__slug="advisor",
            profile__availability_spans__status="no",
            profile__availability_spans__end_date__isnull=True,
        )
        .select_related("profile")
        .order_by("last_name", "first_name", "email")
    )


def advisor_availability_split(advisee):
    """Split :func:`eligible_advisors` into ``(available, unknown)``.

    ``available`` are those who declared "Yes" for the ``advisor`` function;
    ``unknown`` are the rest (never reported — this includes scholar-track
    advisors, who don't carry availability spans). Those who declared "No" are
    already dropped by :func:`eligible_advisors`. Both lists keep the query's
    ordering. Used to group the advisor picker so unreported analysts sit in a
    separate "Unknown availability" section.
    """
    users = list(eligible_advisors(advisee))
    # Lazy import: availability is a separate app; avoid an import cycle at load.
    from availability.models import AnalystFunction, AvailabilitySpan

    fn = AnalystFunction.objects.filter(slug="advisor").first()
    yes_ids: set[int] = set()
    if fn is not None and users:
        yes_ids = set(
            AvailabilitySpan.objects.filter(
                function=fn,
                status=AvailabilitySpan.Status.YES,
                end_date__isnull=True,
                profile__user__in=users,
            ).values_list("profile__user_id", flat=True)
        )
    available = [u for u in users if u.pk in yes_ids]
    unknown = [u for u in users if u.pk not in yes_ids]
    return available, unknown


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
