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
