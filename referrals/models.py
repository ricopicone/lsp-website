"""The Referral Coordinator's workflow (task #229).

The public Find-an-Analyst form (accounts app) is the intake; everything
after lands here: each submission becomes a tracked :class:`ReferralRequest`,
the referral list of clinicians lives in-site (:class:`ReferralListMember`),
clinician responses aggregate on the request (:class:`ReferralResponse`), and
every outgoing message is an editable :class:`MessageTemplate` seeded from the
coordinator's own wording.

Per the do-not-over-automate principle, each sending step has a per-step
auto/review toggle on :class:`ReferralSettings` — "auto" fires on its own,
"review first" prepares a draft the coordinator adjusts and sends. Requests
are visible only to the Referral Coordinator (plus superusers) and are
redacted after the retention window (see ``services.purge_expired``).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Mode(models.TextChoices):
    """Per-step automation toggle: fire on its own, or draft for review."""

    AUTO = "auto", _("Automatic")
    REVIEW = "review", _("Review first")


class ReferralSettings(models.Model):
    """Singleton: the coordinator's workflow knobs (changeable anytime)."""

    ack_mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.AUTO,
        verbose_name="Acknowledgment (step 2)",
        help_text="The process reply to the requester after they submit.",
    )
    distribution_mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.REVIEW,
        verbose_name="Distribution (step 3)",
        help_text="Sending the anonymized request to the referral list. "
        "Automatic sends it as soon as the request arrives; review first "
        "waits for you to press Distribute on the request page.",
    )
    followup_mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.REVIEW,
        verbose_name="Follow-up (step 5)",
        help_text="The reply to the requester with available clinicians. "
        "Automatic sends the assembled draft when the response window "
        "closes; review first leaves it for you to adjust and send.",
    )
    onboarding_mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.AUTO,
        verbose_name="New-member onboarding",
        help_text="The New Member Instructions sent when a clinician is "
        "added to the referral list.",
    )
    response_window_days = models.PositiveSmallIntegerField(
        default=10,
        help_text="How long clinicians have to respond after distribution.",
    )
    retention_months = models.PositiveSmallIntegerField(
        default=12,
        help_text="Months after a request is replied/closed before its "
        "identifying details are redacted.",
    )
    held_escalation_days = models.PositiveSmallIntegerField(
        default=3,
        help_text="Days a held submission may sit unreviewed before the "
        "coordinator is emailed about it. Held requests otherwise only "
        "ring the notification bell.",
    )

    class Meta:
        verbose_name = "Referral settings"
        verbose_name_plural = "Referral settings"

    def __str__(self) -> str:
        return "Referral settings"

    @classmethod
    def load(cls) -> ReferralSettings:
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class MessageTemplate(models.Model):
    """An editable outgoing message, seeded from the coordinator's wording.

    Bodies are plain text with ``{placeholder}`` tokens substituted at send
    time (see ``services.render_template``); unknown tokens are left intact,
    so an edit can never crash a send.
    """

    class Key(models.TextChoices):
        ACKNOWLEDGMENT = "acknowledgment", _("Acknowledgment (process reply)")
        DISTRIBUTION = "distribution", _("Distribution to the referral list")
        FOLLOWUP_MANY = "followup_many", _("Follow-up — several clinicians")
        FOLLOWUP_ONE = "followup_one", _("Follow-up — a single clinician")
        FOLLOWUP_NONE = "followup_none", _("Follow-up — no responses")
        ONBOARDING = "onboarding", _("New Member Instructions")

    key = models.CharField(max_length=30, choices=Key.choices, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.get_key_display()

    @classmethod
    def get(cls, key: str) -> MessageTemplate:
        """Fetch a template; if it was deleted, restore it from the seed."""
        obj = cls.objects.filter(key=key).first()
        if obj is None:
            from .seed_templates import SEED_TEMPLATES

            subject, body = SEED_TEMPLATES[key]
            obj = cls.objects.create(key=key, subject=subject, body=body)
        return obj


class ReferralRequest(models.Model):
    """One Find-an-Analyst submission, tracked through the referral lifecycle.

    Visible only to the Referral Coordinator. ``reference`` is the stable
    "number of the referral" quoted to clinicians (never the requester's
    name); requester-identifying fields are redacted after retention.
    """

    class Status(models.TextChoices):
        NEW = "new", _("New")
        ACKNOWLEDGED = "acknowledged", _("Acknowledged")
        DISTRIBUTED = "distributed", _("Distributed — collecting responses")
        REPLIED = "replied", _("Replied")
        CLOSED = "closed", _("Closed")
        HELD = "held", _("Held for review")
        JUNK = "junk", _("Junk")

    #: Statuses still on the coordinator's plate.
    OPEN_STATUSES = (Status.NEW, Status.ACKNOWLEDGED, Status.DISTRIBUTED)

    #: Statuses that must never be acknowledged or distributed. Screening
    #: puts a request in HELD; a coordinator puts it in JUNK. Guarded in
    #: services.send_acknowledgment and services.distribute so no future
    #: caller can leak one to the referral list (task #479).
    SUPPRESSED_STATUSES = (Status.HELD, Status.JUNK)

    reference = models.CharField(max_length=20, unique=True, editable=False)

    # Intake (mirrors the Find-an-Analyst form). Name + email are the two
    # fields withheld from clinicians during distribution.
    name = models.CharField(max_length=120)
    pronouns = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)  # blank after redaction
    location = models.CharField(max_length=200)
    language = models.CharField(max_length=80)
    modalities = models.CharField(max_length=200, blank=True)
    additional_information = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    distributed_at = models.DateTimeField(null=True, blank=True)
    distributed_to = models.ManyToManyField(
        "ReferralListMember", blank=True, related_name="distributed_requests",
        help_text="Clinicians who have received this request, whether by the "
                  "original distribution or a later addendum.",
    )
    responses_due_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    # Spam screening (task #479). A held request is not acknowledged and not
    # distributed until a coordinator releases it.
    held_reason = models.TextField(
        blank=True,
        help_text="Why screening held this submission, shown to the "
        "coordinator so they can judge it at a glance.",
    )
    held_at = models.DateTimeField(null=True, blank=True)
    held_escalated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the unreviewed-hold reminder was emailed, so it "
        "is sent only once.",
    )

    coordinator_notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.reference} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._allocate_reference()
        super().save(*args, **kwargs)

    def _allocate_reference(self) -> str:
        """Year-date reference, the coordinator's own convention: ``26-0612``
        for 2026-06-12 (local date), with ``-2``, ``-3``, … appended when more
        than one request arrives the same day."""
        base = timezone.localtime().strftime("%y-%m%d")
        with transaction.atomic():
            taken = set(
                type(self).objects.select_for_update()
                .filter(reference__startswith=base)
                .values_list("reference", flat=True)
            )
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    @property
    def is_purged(self) -> bool:
        return self.purged_at is not None

    @property
    def window_closed(self) -> bool:
        return (
            self.responses_due_at is not None
            and timezone.now() >= self.responses_due_at
        )

    def interested_responses(self):
        return (
            self.responses.filter(available=True)
            .select_related("member__user__profile")
            .order_by("created_at")
        )


class ReferralListMember(models.Model):
    """A clinician on the referral list (the list now lives in-site).

    Practice details are self-service on the member's Profile;
    ``details_override`` is the coordinator's escape hatch — when set it is
    used verbatim in follow-up replies instead of the profile-built block.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_listing",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive members stay on record but receive no requests.",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    onboarded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the New Member Instructions were sent.",
    )
    details_override = models.TextField(
        blank=True,
        help_text="If set, sent to requesters verbatim instead of the "
        "block built from the member's profile.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("user__last_name", "user__first_name")

    def __str__(self) -> str:
        return f"{self.user.get_full_name() or self.user.email}"

    def details_block(self) -> str:
        """The practice-details block a requester receives for this clinician.

        Mirrors the coordinator's historical format (name / title / email /
        phone, plus a website when listed) — built from the profile so the
        member maintains it themselves. Ends with a link to the member's
        public directory profile when they have one. The block is plain
        text; the email layer linkifies URLs and email addresses in the
        HTML alternative (see ``referrals.emails``).
        """
        if self.details_override.strip():
            return self.details_override.strip()
        profile = self.user.profile
        lines = [profile.display_full_name]
        if profile.credentials:
            lines.append(profile.credentials)
        lines.append(profile.public_email or self.user.email)
        if profile.public_phone:
            lines.append(_format_phone(profile.public_phone))
        if profile.website:
            lines.append(profile.website)
        if self.directory_url():
            lines.append(f"Profile: {self.directory_url()}")
        return "\n".join(line for line in lines if line)

    def directory_url(self) -> str:
        """Absolute URL of the member's public directory page, or '' when
        they have none (not a directory role, or opted out of listing)."""
        from django.urls import reverse

        profile = self.user.profile
        if not (profile.public and profile.role in profile.DIRECTORY_ROLES):
            return ""
        return settings.SITE_BASE_URL.rstrip("/") + reverse(
            "directory_detail", args=[profile.directory_slug],
        )


def _format_phone(phone) -> str:
    """Human-readable phone: national format for US numbers ((206) 555-0100),
    international for the rest (+33 1 23 45 67 89)."""
    try:
        if getattr(phone, "country_code", None) == 1:
            return phone.as_national
        return phone.as_international
    except Exception:
        return str(phone)


class ReferralResponse(models.Model):
    """A clinician's response to a distributed request (step 4).

    Created by the clinician on the in-site respond page, or recorded
    manually by the coordinator (``recorded_by``).
    """

    request = models.ForeignKey(
        ReferralRequest, on_delete=models.CASCADE, related_name="responses",
    )
    member = models.ForeignKey(
        ReferralListMember, on_delete=models.CASCADE, related_name="responses",
    )
    available = models.BooleanField(default=True)
    message = models.TextField(
        blank=True, help_text="Optional note to the coordinator.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Set when the coordinator recorded this on the "
        "clinician's behalf.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("request", "member"), name="unique_response_per_member",
            ),
        ]
        ordering = ("created_at",)

    def __str__(self) -> str:
        verb = "available" if self.available else "not available"
        return f"{self.member} — {verb} for {self.request.reference}"


class BlockedSubmission(models.Model):
    """One Find-an-Analyst submission rejected by a transport-level check.

    Deliberately content-free: a timestamp and a reason, nothing else. No
    address, no IP, no submitted text. It exists only so the coordinator can
    see a hit rate — without it, a filter that silently broke and started
    eating real requests would look exactly like a filter that is working
    (task #479).
    """

    class Reason(models.TextChoices):
        HONEYPOT = "honeypot", _("Honeypot field filled")
        TIMING = "timing", _("Submitted too fast")
        RATE_LIMIT = "rate_limit", _("Rate limit")

    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.get_reason_display()} at {self.created_at:%Y-%m-%d %H:%M}"
