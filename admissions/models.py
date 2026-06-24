"""The formation pipeline — applications to join, and advancement within.

Mirrors the LSP Analyst- and Scholar-formation guidelines. Section I (apply to
join): an applicant submits a letter of intent + CV, has two interviews with
Analysts of the School, and the Meeting of the Analysts decides — acceptance
admits them as a Precandidate. The later steps (palimpsest: Precandidate →
Candidate; passage: Candidate → Analyst/Scholar) are :class:`Advancement`
demandes, recommended by the member's Advisor and decided by the same Meeting
of the Analysts. Every role change routes through
``accounts.membership.record_membership_change``.

The whole pipeline — admissions *and* advancement — belongs to the **Meeting of
the Analysts** (per ``content/pages/about.md``: "they review admissions
materials … and make admission decisions … this meeting considers demands for
palimpsests and passages"), so the review surfaces are gated by
``workgroups.permissions.is_meeting_of_analysts``.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .storage import cv_storage


def step_label_for(kind, role) -> str:
    """The track-aware display name for a formation step. ``Palimpsest`` is the
    same on both tracks; the passage step is a **Passage** for the Analyst track
    and a **Traversée** for the Scholar track."""
    if kind == "palimpsest":
        return "Palimpsest"
    from accounts.models import Profile
    return "Traversée" if role in Profile.SCHOLAR_TRACK_ROLES else "Passage"


class Application(models.Model):
    """One person's application to join a formation track."""

    class Track(models.TextChoices):
        ANALYST = "analyst", _("Analyst formation")
        SCHOLAR = "scholar", _("Scholar formation")

    class Background(models.TextChoices):
        ACADEMIC = "academic", _("Academic background")
        CLINICAL = "clinical", _("Clinical background")

    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Submitted — awaiting review")
        INTERVIEWING = "interviewing", _("In interviews")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Not accepted")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    #: The role an accepted applicant is admitted into, per track.
    ADMIT_ROLE = {
        Track.ANALYST: "pre_candidate",
        Track.SCHOLAR: "pre_candidate_scholar",
    }

    OPEN_STATUSES = (Status.SUBMITTED, Status.INTERVIEWING)

    applicant = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="application",
    )
    track = models.CharField(max_length=10, choices=Track.choices)

    # Eligibility (analyst track distinguishes academic vs clinical background;
    # the scholar track instead attests a year of personal analysis).
    background = models.CharField(
        max_length=10, choices=Background.choices, blank=True,
        help_text="Analyst track: academic or clinical background.",
    )
    eligibility_note = models.CharField(
        max_length=255, blank=True,
        help_text="Degree / licensure (analyst) or where the year of personal "
        "analysis took place (scholar).",
    )

    # Package
    letter_of_intent = models.TextField(
        help_text="Interest and goals in the study of Freudian and Lacanian "
        "psychoanalysis and the chosen formation.",
    )
    cv = models.FileField(upload_to="cv/%Y/", storage=cv_storage, blank=True)

    status = models.CharField(
        max_length=14, choices=Status.choices, default=Status.SUBMITTED, db_index=True,
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="application_decisions",
    )
    decision_note = models.TextField(blank=True)
    staff_notes = models.TextField(blank=True, help_text="Internal reviewer notes.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-submitted_at",)

    def __str__(self):
        return f"{self.applicant} — {self.get_track_display()} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def admit_role(self) -> str:
        return self.ADMIT_ROLE[self.track]


class ApplicationInterview(models.Model):
    """One of the (two) application interviews — an Analyst of the School and
    their report. The $50 interview fee is paid to the analyst directly and is
    not processed by the site."""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="interviews",
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="application_interviews",
    )
    completed_at = models.DateField(
        null=True, blank=True, help_text="Date the interview took place; blank = pending.",
    )
    report = models.TextField(blank=True, help_text="The interviewer's report / recommendation.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("application", "interviewer"),
                name="admissions_one_interview_per_interviewer",
            ),
        ]

    def __str__(self):
        state = "completed" if self.completed_at else "pending"
        return f"{self.application.applicant} ↔ {self.interviewer} ({state})"

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None and bool(self.report.strip())


class Advancement(models.Model):
    """A member's demande to advance a step in formation.

    **Palimpsest** (Precandidate → Candidate) is the step built first; the model
    is generic so **Passage / Traversée** (Candidate → Analyst / Scholar) reuses
    it. Flow: the member opens a demande → their Advisor writes a recommendation
    and **presents it to the Meeting of the Analysts** (reminder emails nudge the
    Advisor until they do) → the Meeting decides. Approval advances the member's
    role via ``accounts.membership.record_membership_change``.
    """

    class Kind(models.TextChoices):
        PALIMPSEST = "palimpsest", _("Palimpsest (Precandidate → Candidate)")
        PASSAGE = "passage", _("Passage / Traversée (Candidate → Analyst / Scholar)")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested — awaiting advisor's recommendation")
        PRESENTED = "presented", _("Presented to the Meeting of the Analysts")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Not approved")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    #: The formation step a member at a given role is requesting.
    KIND_FOR_ROLE = {
        "pre_candidate": Kind.PALIMPSEST,
        "pre_candidate_scholar": Kind.PALIMPSEST,
        "candidate": Kind.PASSAGE,
        "candidate_scholar": Kind.PASSAGE,
    }
    #: current role → role advanced into, per kind.
    ADVANCE_ROLE = {
        Kind.PALIMPSEST: {
            "pre_candidate": "candidate",
            "pre_candidate_scholar": "candidate_scholar",
        },
        Kind.PASSAGE: {
            "candidate": "analyst",
            "candidate_scholar": "scholar",
        },
    }
    OPEN_STATUSES = (Status.REQUESTED, Status.PRESENTED)

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="advancements",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PALIMPSEST)
    #: The role the member held when they opened the demande — the basis for
    #: ``advance_role`` (so a later role edit can't silently change the target).
    from_role = models.CharField(max_length=32)

    # The demande
    statement = models.TextField(
        help_text="The member's statement — why they are ready for this step.",
    )
    palimpsest = models.FileField(
        upload_to="palimpsest/%Y/", storage=cv_storage, blank=True,
        help_text="Optional written palimpsest / supporting document (private).",
    )

    # Advisor recommendation + presentation to the Meeting
    advisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="advancements_advised",
        help_text="The member's Advisor at the time of the demande.",
    )
    recommendation = models.TextField(
        blank=True, help_text="The Advisor's recommendation to the Meeting.",
    )
    presented_at = models.DateField(
        null=True, blank=True,
        help_text="Date the Advisor presented the demande to the Meeting "
        "of the Analysts; blank = not yet presented.",
    )
    last_reminded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the Advisor was last reminded to present (reminder cron).",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True,
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="advancement_decisions",
    )
    decision_note = models.TextField(blank=True)
    staff_notes = models.TextField(blank=True, help_text="Internal reviewer notes.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-requested_at",)
        constraints = [
            # One open demande per member at a time.
            models.UniqueConstraint(
                fields=("member",),
                condition=models.Q(status__in=("requested", "presented")),
                name="admissions_one_open_advancement_per_member",
            ),
        ]

    def __str__(self):
        return f"{self.member} — {self.get_kind_display()} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def advance_role(self) -> str | None:
        """The role this demande advances the member into (None if their
        ``from_role`` has no mapping for this kind)."""
        return self.ADVANCE_ROLE.get(self.kind, {}).get(self.from_role)

    @property
    def step_label(self) -> str:
        """The track-aware name of this formation step. The passage step is a
        **Passage** on the Analyst track and a **Traversée** on the Scholar
        track; the palimpsest is the same word on both. Keyed off ``from_role``
        (snapshotted when the demande opened) so it's stable after advancement."""
        return step_label_for(self.kind, self.from_role)


# ---------------------------------------------------------------------------
# Applications Coordinator — editable outgoing messages
# ---------------------------------------------------------------------------

class MessageTemplate(models.Model):
    """An editable message the Applications Coordinator sends while facilitating
    admissions for the Meeting of Analysts.

    Same shape as ``referrals.MessageTemplate``: a ``{placeholder}`` body the
    coordinator can reword, restorable from the seed if deleted. Today: the
    nudge to an interviewer whose report is still outstanding.
    """

    class Key(models.TextChoices):
        INTERVIEWER_NUDGE = "interviewer_nudge", _("Interviewer report reminder")

    key = models.CharField(max_length=40, choices=Key.choices, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.get_key_display()

    @classmethod
    def get(cls, key: str) -> MessageTemplate:
        """Fetch a template; restore it from the seed if it was deleted."""
        obj = cls.objects.filter(key=key).first()
        if obj is None:
            from .seed_templates import SEED_TEMPLATES

            subject, body = SEED_TEMPLATES[key]
            obj = cls.objects.create(key=key, subject=subject, body=body)
        return obj
