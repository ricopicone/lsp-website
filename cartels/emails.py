"""Transactional emails for the cartel workflow (CART-4).

Fail-soft: a mail error must never break the workflow action (mirrors the
Stripe-webhook email handling). Sends from DEFAULT_FROM_EMAIL with
Reply-To: SUPPORT_EMAIL.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def _send(*, subject: str, body: str, to: list[str]) -> None:
    to = [addr for addr in to if addr]
    if not to:
        return
    try:
        EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
            reply_to=[settings.SUPPORT_EMAIL],
        ).send(fail_silently=False)
    except Exception:  # noqa: BLE001 — never let mail break the workflow
        logger.exception("Cartel email send failed (subject=%r, to=%r)", subject, to)


def _coordinator_emails():
    from accounts.models import User
    from core.models import StaffRole

    return list(
        User.objects.filter(staff_roles__key=StaffRole.CARTEL_COORDINATOR)
        .values_list("email", flat=True)
    )


def notify_coordinator_of_proposal(cartel, url: str) -> None:
    _send(
        subject=f"[LSP] Cartel proposal: {cartel.workgroup.name}",
        body=(
            f"{cartel.generator.get_full_name() or cartel.generator.email} proposed a "
            f"cartel for review.\n\n"
            f"Name: {cartel.workgroup.name}\n"
            f"Guiding question: {cartel.guiding_question or '(none)'}\n\n"
            f"Review it: {url}\n"
        ),
        to=_coordinator_emails(),
    )


def notify_generator_of_decision(cartel, url: str) -> None:
    if cartel.generator is None:
        return
    if cartel.status == cartel.Status.OPEN:
        body = (
            f"Your cartel '{cartel.workgroup.name}' was approved and is now open "
            f"for membership.\n\n{url}\n"
        )
        subject = f"[LSP] Cartel approved: {cartel.workgroup.name}"
    else:
        body = (
            f"Your cartel proposal '{cartel.workgroup.name}' was not approved.\n\n"
            f"{cartel.review_note or ''}\n"
        )
        subject = f"[LSP] Cartel proposal declined: {cartel.workgroup.name}"
    _send(subject=subject, body=body, to=[cartel.generator.email])


def notify_invitee(cartel, invited_user, url: str) -> None:
    _send(
        subject=f"[LSP] You're invited to the cartel '{cartel.workgroup.name}'",
        body=(
            f"You were invited to join the cartel '{cartel.workgroup.name}'.\n"
            f"Guiding question: {cartel.guiding_question or '(none)'}\n\n"
            f"Accept the invitation: {url}\n"
        ),
        to=[invited_user.email],
    )


def notify_members_of_application(cartel, applicant, url: str) -> None:
    member_emails = list(
        cartel.workgroup.active_members().values_list("user__email", flat=True)
    )
    _send(
        subject=f"[LSP] New application to join '{cartel.workgroup.name}'",
        body=(
            f"{applicant.get_full_name() or applicant.email} applied to join the "
            f"cartel '{cartel.workgroup.name}'.\n\n"
            f"Review applications: {url}\n"
        ),
        to=member_emails,
    )


def invite_external_plus_one(external, signup_url: str) -> None:
    cartel = external.cartel
    _send(
        subject=f"[LSP] Invitation to join the cartel '{cartel.workgroup.name}'",
        body=(
            f"You've been named the plus-one for the LSP cartel "
            f"'{cartel.workgroup.name}'.\n\n"
            f"Create an account to join the cartel's workspace: {signup_url}\n"
        ),
        to=[external.email],
    )


def notify_applicant_of_decision(join_request, url: str) -> None:
    cartel = join_request.cartel
    accepted = join_request.status == join_request.Status.ACCEPTED
    _send(
        subject=(
            f"[LSP] You've joined '{cartel.workgroup.name}'" if accepted
            else f"[LSP] Update on your application to '{cartel.workgroup.name}'"
        ),
        body=(
            (f"You were accepted into the cartel '{cartel.workgroup.name}'.\n\n{url}\n")
            if accepted else
            (f"Your application to '{cartel.workgroup.name}' was not accepted at this time.\n")
        ),
        to=[join_request.applicant.email],
    )
