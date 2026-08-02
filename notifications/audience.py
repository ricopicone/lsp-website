"""Who sees a row for a category on the notification settings page.

Separate from :mod:`notifications.categories` on purpose. That module is the
delivery table — ``default_email_for`` there changes what dispatch *sends*.
This module changes only what the settings page *renders*: a hidden category
still notifies normally if it ever fires, which is what makes hiding safe.

A category absent from :data:`AUDIENCE` is visible to everyone — the safe
default, so adding a category never accidentally hides it. Predicates import
their gates lazily so ``notifications`` keeps no module-level dependency on
``committees`` / ``referrals`` / ``availability`` / ``workgroups``.

Only categories with a *crisp* audience are listed. One that reaches both a
queue and a member (cartel proposal review, which also notifies the cartel's
generator; event change review and admissions applications, which also reach
the submitter) stays visible to everyone rather than being hidden from someone
who genuinely receives it.
"""

from __future__ import annotations

from collections.abc import Callable

from .categories import CATEGORY_META, Category


def _is_board(user) -> bool:
    from committees.permissions import is_on_committee

    return is_on_committee(user, "board")


def _is_site_staff(user) -> bool:
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER)


def _takes_referrals(user) -> bool:
    """On the referral list, or the coordinator who fields held submissions —
    both audiences share this category."""
    from core.access import has_staff_role
    from core.models import StaffRole
    from referrals.models import ReferralListMember

    if has_staff_role(user, StaffRole.REFERRAL_COORDINATOR):
        return True
    return ReferralListMember.objects.filter(user=user, is_active=True).exists()


def _is_meeting_of_analysts(user) -> bool:
    from workgroups.permissions import is_meeting_of_analysts

    return is_meeting_of_analysts(user)


def _has_availability_row(user) -> bool:
    from availability import services

    profile = getattr(user, "profile", None)
    return profile is not None and services.is_eligible(profile)


def _owes_tuition(user) -> bool:
    profile = getattr(user, "profile", None)
    return bool(profile and profile.owes_tuition)


#: category -> predicate. Absent means "everyone sees it".
AUDIENCE: dict[str, Callable[[object], bool]] = {
    Category.TUITION_PLAN_REVIEW: _is_board,
    Category.SUGGESTION_FILED: _is_site_staff,
    Category.REFERRAL_REQUEST: _takes_referrals,
    Category.EXTERNAL_CONTROL_ANALYST: _is_meeting_of_analysts,
    Category.AVAILABILITY_REVIEW: _has_availability_row,
    Category.TUITION_REMINDER: _owes_tuition,
    Category.TUITION_PLAN_DECISION: _owes_tuition,
}


def applies(user, category: str) -> bool:
    """Whether ``user`` should see a settings row for ``category``."""
    if getattr(user, "is_superuser", False):
        return True
    predicate = AUDIENCE.get(str(category))
    return True if predicate is None else bool(predicate(user))


def visible_categories(user) -> list[str]:
    """The categories to show ``user``, in ``CATEGORY_META`` order.

    The settings page renders from this **and** saves from it — a row that
    isn't rendered must not be written, or saving would silently switch it off.
    """
    return [c for c in CATEGORY_META if applies(user, c)]
