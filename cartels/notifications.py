"""Notification wrappers for the cartel workflow.

Single-recipient events (decision, invitation, applicant decision) raise an
in-app bell row and send the existing email when the member's preference
allows. Multi-recipient events (proposal review, applications) raise bell rows
for each member and keep their existing batched staff email — that email is an
operational signal to a small group, not member-facing noise.
"""

from __future__ import annotations

from notifications.categories import Category
from notifications.dispatch import notify

from . import emails


def _name(user) -> str:
    return (user.get_full_name() if user else "") or "Someone"


def _coordinator_users():
    from accounts.models import User
    from core.models import StaffRole
    return list(User.objects.filter(staff_roles__key=StaffRole.CARTEL_COORDINATOR))


def _pc_users():
    from accounts.models import User
    return list(
        User.objects.filter(
            workgroup_memberships__end_date__isnull=True,
            workgroup_memberships__workgroup__committee__slug="programming-committee",
        ).distinct()
    )


def proposal(cartel, url: str) -> None:
    recipients = {u.id: u for u in _coordinator_users()}
    recipients.update({u.id: u for u in _pc_users()})
    for user in recipients.values():
        notify(
            user, Category.CARTEL_PROPOSAL,
            title=f"Cartel proposal: {cartel.workgroup.name}",
            url=url, target=cartel, email=False, dedupe=True,
        )
    emails.notify_proposal(cartel, url)


def forming_started(cartel, url: str) -> None:
    """TASK 8 STUB (task #392): a cartel begins forming (propose view). For
    now this only notifies the Cartel Coordinator, so they're aware a new
    cartel is gathering members even though the PC has nothing to review yet
    (that happens later, at submit). Task 8 owns the full member-facing
    version of this notification (e.g. broadcasting the open call to the
    school) — refine/replace this stub there."""
    for user in _coordinator_users():
        notify(
            user, Category.CARTEL_PROPOSAL,
            title=f"Cartel forming: {cartel.workgroup.name}",
            url=url, target=cartel, email=False, dedupe=True,
        )


def submitted(cartel, url: str) -> None:
    """TASK 8 STUB (task #392): a cartel is submitted to the PC for
    registration. For now this delegates to the existing ``proposal()``
    notification (Cartel Coordinator + Programming Committee, batched staff
    email) — the same audience that used to be notified at propose-time.
    Task 8 owns building a dedicated "submitted for registration" email/bell
    copy distinct from the original proposal-review one; refine/replace this
    stub there."""
    proposal(cartel, url)


def coordinator_feedback(cartel, url: str) -> None:
    recipients = {u.id: u for u in _pc_users()}
    if cartel.generator_id:
        recipients[cartel.generator_id] = cartel.generator
    for user in recipients.values():
        notify(
            user, Category.CARTEL_PROPOSAL,
            title=f"Coordinator feedback: {cartel.workgroup.name}",
            url=url, target=cartel, email=False, dedupe=True,
        )
    emails.notify_coordinator_feedback(cartel, url)


def generator_decision(cartel, url: str) -> None:
    if cartel.generator is None:
        emails.notify_generator_of_decision(cartel, url)
        return
    approved = cartel.status == cartel.Status.OPEN
    notify(
        cartel.generator, Category.CARTEL_DECISION,
        title=(
            f"Cartel approved: {cartel.workgroup.name}" if approved
            else f"Cartel proposal declined: {cartel.workgroup.name}"
        ),
        url=url, target=cartel,
        email_fn=lambda: emails.notify_generator_of_decision(cartel, url),
    )


def invitee(cartel, invited_user, url: str) -> None:
    notify(
        invited_user, Category.CARTEL_INVITE,
        title=f"You're invited to the cartel '{cartel.workgroup.name}'",
        url=url, target=cartel,
        email_fn=lambda: emails.notify_invitee(cartel, invited_user, url),
    )


def members_of_application(cartel, applicant, url: str) -> None:
    for membership in cartel.workgroup.active_members().select_related("user"):
        notify(
            membership.user, Category.CARTEL_APPLICATION,
            title=f"{_name(applicant)} applied to join '{cartel.workgroup.name}'",
            url=url, target=cartel, email=False, dedupe=True,
        )
    emails.notify_members_of_application(cartel, applicant, url)


def external_plus_one(external, signup_url: str) -> None:
    # No user account yet — email only.
    emails.invite_external_plus_one(external, signup_url)


def applicant_decision(join_request, url: str) -> None:
    cartel = join_request.workgroup.cartel
    accepted = join_request.status == join_request.Status.ACCEPTED
    notify(
        join_request.applicant, Category.CARTEL_DECISION,
        title=(
            f"You've joined '{cartel.workgroup.name}'" if accepted
            else f"Update on your application to '{cartel.workgroup.name}'"
        ),
        url=url, target=join_request,
        email_fn=lambda: emails.notify_applicant_of_decision(join_request, url),
    )
