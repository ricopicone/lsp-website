"""Notifications for the events app: the faculty editing review loop (#295)
and event proposals entering review and being decided (task #820).

Routed through the central :func:`notifications.dispatch.notify` chokepoint so
each message lands on the bell and (preference-gated) in email.
"""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify


def _program_committee_users():
    """Currently-serving Programming Committee members (the reviewers)."""
    from workgroups.models import WorkgroupMembership
    qs = (
        WorkgroupMembership.objects.serving()
        .filter(workgroup__committee__slug="programming-committee")
        .select_related("user")
    )
    # De-dupe in case someone holds more than one role on the committee.
    return {m.user for m in qs if m.user_id}


def notify_change_submitted(change_request):
    """Tell the Programming Committee a content change awaits review."""
    event = change_request.event
    actor = change_request.proposed_by
    fields = ", ".join(lbl for lbl, _o, _n in change_request.field_changes()) or "content"
    url = reverse("program_admin_changes")
    title = f"Change to “{event.title}” awaiting review"
    who = (actor.get_full_name() or actor.email) if actor else "A faculty member"
    body = f"{who} submitted changes to {fields} for committee review."
    for reviewer in _program_committee_users():
        if actor and reviewer == actor:
            continue
        notify(
            reviewer, Category.EVENT_CHANGE_REVIEW,
            title=title, body=body, url=url, actor=actor, target=change_request,
        )


def notify_change_decided(change_request):
    """Tell the proposer the committee approved or declined their change."""
    proposer = change_request.proposed_by
    if not proposer:
        return
    event = change_request.event
    approved = change_request.status == change_request.Status.APPROVED
    if approved:
        title = f"Your change to “{event.title}” was approved"
        body = "The Program Committee approved your change; it is now live."
    else:
        title = f"Your change to “{event.title}” was declined"
        body = "The Program Committee declined your change."
        if change_request.review_note:
            body += f" Note: {change_request.review_note}"
    notify(
        proposer, Category.EVENT_CHANGE_REVIEW,
        title=title, body=body,
        url=reverse("events:detail", args=[event.slug]),
        actor=change_request.reviewed_by, target=change_request,
    )


def notify_proposal_submitted(proposal, *, resubmitted=False):
    """Tell the Program Committee a member's proposal awaits review (task #820)."""
    actor = proposal.proposed_by
    who = (actor.get_full_name() or actor.email) if actor else "A member"
    kind = proposal.get_event_type_display().lower()
    verb = "resubmitted" if resubmitted else "submitted"
    title = f"Proposal: “{proposal.title}”"
    body = f"{who} {verb} a {kind} proposal for review."
    url = reverse("program_admin_proposals")
    for reviewer in _program_committee_users():
        if actor and reviewer == actor:
            continue
        notify(
            reviewer, Category.EVENT_PROPOSAL,
            title=title, body=body, url=url, actor=actor, target=proposal,
        )


def notify_proposal_decided(proposal):
    """Tell the proposer the committee approved or declined their proposal."""
    proposer = proposal.proposed_by
    if not proposer or proposer == proposal.reviewed_by:
        return
    if proposal.status == proposal.Status.APPROVED and proposal.minted_event_id:
        title = f"Your proposal “{proposal.title}” was approved"
        body = "The Program Committee approved it, and the event has been created."
        url = reverse("events:detail", args=[proposal.minted_event.slug])
    else:
        title = f"Your proposal “{proposal.title}” was declined"
        body = "The Program Committee declined it. You can edit it and resubmit."
        if proposal.review_note:
            body += f" Their note: {proposal.review_note}"
        url = reverse("formation:formation") + "?tab=proposals"
    notify(
        proposer, Category.EVENT_PROPOSAL,
        title=title, body=body, url=url,
        actor=proposal.reviewed_by, target=proposal,
    )
