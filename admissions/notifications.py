"""Notification wrappers for the application (intake) process.

Each adds an in-app bell row and, when the member's preference allows, sends
the existing admissions email (passed as ``email_fn``). Call these instead of
``admissions.emails`` directly.

The ongoing-formation (advancement demande) notifications live in
``formation.notifications``.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails

# --- Applicant-facing -------------------------------------------------------

def application_submitted(application) -> None:
    notify(
        application.applicant, Category.ADMISSIONS_APPLICATION,
        title="We received your application",
        url=reverse("admissions:status"), target=application,
        email_fn=lambda: emails.send_application_submitted(application),
    )


def application_decision(application) -> None:
    notify(
        application.applicant, Category.ADMISSIONS_DECISION,
        title="A decision on your application",
        url=reverse("admissions:status"), target=application,
        email_fn=lambda: emails.send_application_decision(application),
    )
