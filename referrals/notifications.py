"""Bell + email dispatch for the referral workflow (notifications center)."""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails


def referral_request(user, request_obj, subject: str, body: str) -> None:
    """Tell a referral-list clinician about a newly distributed request."""
    notify(
        user, Category.REFERRAL_REQUEST,
        title=f"Referral request {request_obj.reference}",
        body="A new anonymized referral request is open for responses.",
        url=reverse("referrals:respond", args=[request_obj.reference]),
        target=request_obj,
        dedupe=True,
        email_fn=lambda: emails.send_to_clinician(user, subject, body),
    )


def referral_held(request_obj) -> None:
    """Tell the Referral Coordinator a submission was held for review.

    Bell only, by design (task #479) — held requests are usually junk and
    should not add to the coordinator's inbox. A hold left unreviewed is
    escalated to email by ``process_referrals``.

    Superusers are deliberately *not* included: they implicitly pass the
    permission gate, but bell-notifying every superuser about every bot
    submission is noise. Only explicit role holders are told.
    """
    from core.models import StaffRole

    role = StaffRole.objects.filter(
        key=StaffRole.REFERRAL_COORDINATOR,
    ).first()
    if role is None:
        return
    for user in role.holders.all():
        notify(
            user, Category.REFERRAL_REQUEST,
            title=f"Referral request {request_obj.reference} held for review",
            body=request_obj.held_reason,
            url=reverse("referrals:detail", args=[request_obj.reference]),
            target=request_obj,
            dedupe=True,
        )
