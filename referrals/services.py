"""The referral workflow's five steps, as callable services.

Steps (the coordinator's own numbering, from her process):

1–2. ``intake`` — the Find-an-Analyst form submission becomes a tracked
     :class:`ReferralRequest`; the inquiry goes to the referrals mailbox and
     (in auto mode) the requester gets the process reply.
3.   ``distribute`` — the anonymized request (name + email withheld) goes to
     every active clinician on the referral list, individually, with a link
     to respond on the site.
4.   Clinicians respond on the respond page (or the coordinator records a
     response manually); responses aggregate on the request.
5.   ``build_followup`` + ``send_followup`` — the reply to the requester,
     assembled from the right template variant with each available
     clinician's practice details filled in.

Every step that sends respects the per-step auto/review toggle on
:class:`ReferralSettings`; callers in views invoke these directly when the
coordinator presses the button (review mode), while ``intake`` and the
``process_referrals`` cron invoke them when the toggle says auto.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.conf import settings as django_settings
from django.urls import reverse
from django.utils import timezone

from . import emails, notifications, screening
from .models import (
    MessageTemplate,
    Mode,
    ReferralAddendum,
    ReferralListMember,
    ReferralRequest,
    ReferralSettings,
)

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"\{([a-z_]+)\}")


class SuppressedStatusError(RuntimeError):
    """Raised when a held or junk request is asked to send something.

    The hold in ``intake`` is the fix; this is what keeps it fixed. Any
    future caller — cron, view, admin action — hits this rather than
    quietly mailing 36 clinicians about a bot submission (task #479).
    """


def _refuse_if_suppressed(req: ReferralRequest, action: str) -> None:
    if req.status in ReferralRequest.SUPPRESSED_STATUSES:
        raise SuppressedStatusError(
            f"Refusing to {action} {req.reference}: status is "
            f"{req.get_status_display()}."
        )


def render_template(text: str, context: dict) -> str:
    """Substitute ``{token}`` placeholders for keys present in ``context``.

    Unknown tokens (and any other braces) are left untouched, so a hand-edited
    template can never crash a send.
    """
    return _TOKEN.sub(
        lambda m: str(context[m.group(1)]) if m.group(1) in context else m.group(0),
        text,
    )


def _absolute(path: str) -> str:
    return django_settings.SITE_BASE_URL.rstrip("/") + path


def intake(data: dict) -> ReferralRequest:
    """Steps 1–2: persist the submission, alert the coordinator, acknowledge.

    The record is the one thing that must succeed; either email failing is
    logged but never bubbles up to the form (the request is on the dashboard
    regardless).
    """
    config = ReferralSettings.load()
    # Duplicate-submit guard: a slow form response can invite repeated clicks,
    # each of which would otherwise create its own request (and, in auto mode,
    # email the whole referral list again). If an identical submission landed in
    # the last minute, return it instead of creating — and skip re-sending.
    recent = (
        ReferralRequest.objects.filter(
            name=data["name"],
            email=data["email"],
            created_at__gte=timezone.now() - timedelta(minutes=1),
        )
        .order_by("-created_at")
        .first()
    )
    if recent is not None:
        logger.info(
            "Skipping duplicate referral submission from %s (matches %s)",
            data["email"], recent.reference,
        )
        return recent

    held_reason = screening.screen(data)
    req = ReferralRequest.objects.create(
        name=data["name"],
        pronouns=data.get("pronouns", ""),
        email=data["email"],
        location=data["location"],
        language=data["language"],
        modalities=data.get("modality", ""),
        additional_information=data.get("additional_information", ""),
        status=(
            ReferralRequest.Status.HELD if held_reason
            else ReferralRequest.Status.NEW
        ),
        held_reason=held_reason,
        held_at=timezone.now() if held_reason else None,
    )
    if held_reason:
        # Nothing sends: not the coordinator inquiry, not the acknowledgment
        # to what may be a harvested address, not the distribution.
        logger.info("Held referral %s: %s", req.reference, held_reason)
        try:
            notifications.referral_held(req)
        except Exception:
            logger.exception(
                "Failed to notify the coordinator about held referral %s",
                req.reference,
            )
        return req

    try:
        emails.send_coordinator_inquiry(
            req, _absolute(reverse("referrals:detail", args=[req.reference])),
        )
    except Exception:
        logger.exception(
            "Failed to email referral inquiry %s to the coordinator",
            req.reference,
        )
    if config.ack_mode == Mode.AUTO:
        try:
            send_acknowledgment(req)
        except Exception:
            logger.exception(
                "Failed to send referral acknowledgment for %s", req.reference,
            )
    if config.distribution_mode == Mode.AUTO:
        try:
            distribute(req)
        except Exception:
            logger.exception(
                "Failed to auto-distribute referral %s", req.reference,
            )
    return req


def release(req: ReferralRequest) -> ReferralRequest:
    """Clear a hold and resume the normal post-intake chain.

    A released request is treated exactly as a clean one would have been:
    the coordinator inquiry goes out, and the acknowledgment and
    distribution follow whatever the auto/review toggles say (task #479).
    """
    if req.status != ReferralRequest.Status.HELD:
        return req
    config = ReferralSettings.load()
    req.status = ReferralRequest.Status.NEW
    req.held_reason = ""
    req.held_at = None
    req.held_escalated_at = None
    req.save(update_fields=[
        "status", "held_reason", "held_at", "held_escalated_at",
    ])
    try:
        emails.send_coordinator_inquiry(
            req, _absolute(reverse("referrals:detail", args=[req.reference])),
        )
    except Exception:
        logger.exception(
            "Failed to email released referral %s to the coordinator",
            req.reference,
        )
    if config.ack_mode == Mode.AUTO:
        try:
            send_acknowledgment(req)
        except Exception:
            logger.exception(
                "Failed to acknowledge released referral %s", req.reference,
            )
    if config.distribution_mode == Mode.AUTO:
        try:
            distribute(req)
        except Exception:
            logger.exception(
                "Failed to distribute released referral %s", req.reference,
            )
    req.refresh_from_db()
    return req


def send_acknowledgment(req: ReferralRequest) -> None:
    """Step 2: the process reply to the requester (editable template)."""
    _refuse_if_suppressed(req, "acknowledge")
    tpl = MessageTemplate.get(MessageTemplate.Key.ACKNOWLEDGMENT)
    context = {"name": req.name, "reference": req.reference}
    emails.send_to_requester(
        req,
        render_template(tpl.subject, context),
        render_template(tpl.body, context),
    )
    req.acknowledged_at = timezone.now()
    if req.status == ReferralRequest.Status.NEW:
        req.status = ReferralRequest.Status.ACKNOWLEDGED
    req.save(update_fields=["acknowledged_at", "status"])


def distribute(req: ReferralRequest) -> int:
    """Step 3: the anonymized request to every active list member.

    Each clinician is reached individually (bell + email via the
    notifications center) so their response attributes to them. Returns the
    number of clinicians notified.
    """
    _refuse_if_suppressed(req, "distribute")
    config = ReferralSettings.load()
    members = list(
        ReferralListMember.objects.filter(is_active=True)
        .select_related("user")
    )
    due = timezone.now() + timedelta(days=config.response_window_days)
    tpl = MessageTemplate.get(MessageTemplate.Key.DISTRIBUTION)
    context = {
        "reference": req.reference,
        "pronouns": req.pronouns or "(not given)",
        "location": req.location,
        "language": req.language,
        "modalities": req.modalities or "(not given)",
        "details": req.additional_information,
        "due_date": due.strftime("%B %-d, %Y"),
        "respond_url": _absolute(
            reverse("referrals:respond", args=[req.reference]),
        ),
    }
    subject = render_template(tpl.subject, context)
    body = render_template(tpl.body, context)
    for member in members:
        notifications.referral_request(member.user, req, subject, body)
    req.distributed_at = timezone.now()
    req.responses_due_at = due
    req.status = ReferralRequest.Status.DISTRIBUTED
    req.save(update_fields=["distributed_at", "responses_due_at", "status"])
    req.distributed_to.add(*members)
    return len(members)


def send_addendum(
    req: ReferralRequest,
    text: str,
    audience: str,
    sent_by=None,
    responses_due_at=None,
) -> ReferralAddendum:
    """Tell the clinicians something changed about a distributed request.

    ``audience`` picks between the clinicians the request has already reached
    and the whole active list; either way deactivated members are skipped, and
    everyone reached is recorded on ``req.distributed_to`` so a later addendum
    can target them too (task #531).
    """
    _refuse_if_suppressed(req, "send an addendum for")
    if audience == ReferralAddendum.Audience.DISTRIBUTED:
        members = list(
            req.distributed_to.filter(is_active=True).select_related("user")
        )
    else:
        members = list(
            ReferralListMember.objects.filter(is_active=True)
            .select_related("user")
        )
    if responses_due_at and responses_due_at != req.responses_due_at:
        req.responses_due_at = responses_due_at
        req.save(update_fields=["responses_due_at"])
    due = req.responses_due_at
    tpl = MessageTemplate.get(MessageTemplate.Key.ADDENDUM)
    context = {
        "reference": req.reference,
        "addendum": text,
        "due_date": due.strftime("%B %-d, %Y") if due else "(no date set)",
        "respond_url": _absolute(
            reverse("referrals:respond", args=[req.reference]),
        ),
    }
    subject = render_template(tpl.subject, context)
    body = render_template(tpl.body, context)
    for member in members:
        notifications.referral_addendum(member.user, req, subject, body)
    req.distributed_to.add(*members)
    return ReferralAddendum.objects.create(
        request=req, text=text, audience=audience,
        recipient_count=len(members), sent_by=sent_by,
    )


def build_followup(req: ReferralRequest) -> tuple[str, str]:
    """Step 5 draft: pick the variant by response count and assemble the
    available clinicians' practice details. Returns ``(subject, body)``."""
    available = [r.member for r in req.interested_responses()]
    if not available:
        key = MessageTemplate.Key.FOLLOWUP_NONE
    elif len(available) == 1:
        key = MessageTemplate.Key.FOLLOWUP_ONE
    else:
        key = MessageTemplate.Key.FOLLOWUP_MANY
    tpl = MessageTemplate.get(key)
    context = {
        "name": req.name,
        "reference": req.reference,
        "location": req.location,
        "clinicians": "\n\n".join(m.details_block() for m in available),
    }
    return (
        render_template(tpl.subject, context),
        render_template(tpl.body, context),
    )


def send_followup(req: ReferralRequest, subject: str, body: str) -> None:
    """Step 5 send: the (possibly coordinator-edited) reply to the requester."""
    emails.send_to_requester(req, subject, body)
    req.replied_at = timezone.now()
    if req.status != ReferralRequest.Status.CLOSED:
        req.status = ReferralRequest.Status.REPLIED
    req.save(update_fields=["replied_at", "status"])


def add_to_list(user) -> ReferralListMember:
    """Add (or reactivate) a clinician on the referral list; in auto mode
    this also sends the New Member Instructions on first add."""
    config = ReferralSettings.load()
    member, created = ReferralListMember.objects.get_or_create(user=user)
    if not created and not member.is_active:
        member.is_active = True
        member.save(update_fields=["is_active"])
    if (
        member.onboarded_at is None
        and config.onboarding_mode == Mode.AUTO
    ):
        try:
            send_onboarding(member)
        except Exception:
            logger.exception(
                "Failed to send referral onboarding to %s", user.email,
            )
    return member


def send_onboarding(member: ReferralListMember) -> None:
    """The New Member Instructions to a clinician joining the list."""
    tpl = MessageTemplate.get(MessageTemplate.Key.ONBOARDING)
    context = {
        "name": member.user.profile.display_full_name,
        "profile_url": _absolute(reverse("profile_edit")),
    }
    emails.send_to_clinician(
        member.user,
        render_template(tpl.subject, context),
        render_template(tpl.body, context),
    )
    member.onboarded_at = timezone.now()
    member.save(update_fields=["onboarded_at"])


def purge_expired(now=None) -> int:
    """Privacy retention: redact identifying details on requests whose
    follow-up (or closure) is older than the retention window. Returns the
    number of requests redacted."""
    config = ReferralSettings.load()
    now = now or timezone.now()
    cutoff = now - timedelta(days=30 * config.retention_months)
    expired = ReferralRequest.objects.filter(
        purged_at__isnull=True,
        status__in=(
            ReferralRequest.Status.REPLIED, ReferralRequest.Status.CLOSED,
        ),
    )
    count = 0
    for req in expired:
        done_at = req.closed_at or req.replied_at
        if done_at is None or done_at > cutoff:
            continue
        req.name = "(redacted)"
        req.email = ""
        req.pronouns = ""
        req.additional_information = (
            f"(redacted after {config.retention_months} months)"
        )
        req.coordinator_notes = ""
        req.addenda.update(
            text=f"(redacted after {config.retention_months} months)",
        )
        req.purged_at = now
        req.save(update_fields=[
            "name", "email", "pronouns", "additional_information",
            "coordinator_notes", "purged_at",
        ])
        count += 1
    return count


#: How long a content-free BlockedSubmission row is kept.
BLOCKED_RETENTION_DAYS = 365


def escalate_stale_holds(now=None) -> int:
    """Email the coordinator about holds left unreviewed past the threshold.

    Sends once per request (``held_escalated_at``). Returns how many were
    escalated (task #479).
    """
    config = ReferralSettings.load()
    now = now or timezone.now()
    cutoff = now - timedelta(days=config.held_escalation_days)
    stale = ReferralRequest.objects.filter(
        status=ReferralRequest.Status.HELD,
        held_at__lte=cutoff,
        held_escalated_at__isnull=True,
    )
    count = 0
    for req in stale:
        try:
            emails.send_held_escalation(
                req,
                _absolute(reverse("referrals:detail", args=[req.reference])),
            )
        except Exception:
            logger.exception(
                "Failed to escalate held referral %s", req.reference,
            )
            continue
        req.held_escalated_at = now
        req.save(update_fields=["held_escalated_at"])
        count += 1
    return count


def prune_blocked_submissions(now=None) -> int:
    """Drop blocked-submission counter rows past their retention."""
    from .models import BlockedSubmission

    now = now or timezone.now()
    cutoff = now - timedelta(days=BLOCKED_RETENTION_DAYS)
    deleted, _ = BlockedSubmission.objects.filter(
        created_at__lt=cutoff,
    ).delete()
    return deleted
