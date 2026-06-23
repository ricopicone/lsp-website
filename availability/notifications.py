"""Notification wrappers for the analyst-availability console.

Routes the Applications Coordinator's review request through the notifications
center (in-app bell + preference-gated email), so an analyst who has turned
the email off still sees the prompt in their bell.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails


def request_review(user) -> None:
    """Ask ``user`` to review their availability (bell + email)."""
    subject, body = emails.render_review_request(user)
    notify(
        user,
        Category.AVAILABILITY_REVIEW,
        title="Please review your availability",
        body="Confirm which LSP functions you're available for.",
        url=reverse("profile_edit") + "#availability",
        dedupe=True,
        email_fn=lambda: emails.send_review_request(user, subject, body),
    )
