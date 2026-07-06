"""Applications to join a formation track (the intake side).

Mirrors the LSP Analyst- and Scholar-formation guidelines, Section I (apply to
join): an applicant submits a letter of intent + CV, has two interviews with
Analysts of the School, and the Meeting of the Analysts decides — acceptance
admits them as a Precandidate. The later, ongoing-formation steps (palimpsest:
Precandidate → Candidate; passage: Candidate → Analyst/Scholar) are advancement
demandes and live in the ``formation`` app.

Admissions belongs to the **Meeting of the Analysts** (per
``content/pages/about.md``: "they review admissions materials … and make
admission decisions"), so the review surfaces are gated by
``workgroups.permissions.is_meeting_of_analysts``. This module also carries the
Applications Coordinator's editable message templates and workflow settings.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .storage import cv_storage


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

    #: How many Analysts of the School interview each applicant.
    INTERVIEWS_NEEDED = 2

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
    acknowledged_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the applicant acknowledgment was sent (auto on submit, "
        "or by the coordinator in review-first mode).",
    )
    interviewers_invited_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the call for interviewers went out to available analysts.",
    )
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
    agreed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the analyst agreed to interview (or was assigned).",
    )
    last_reminded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Last weekly reminder to set up / report the interview.",
    )
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
        ACKNOWLEDGMENT = "acknowledgment", _("Applicant acknowledgment (on submit)")
        INVITATION = "invitation", _("Call for interviewers (to analysts)")
        INTRODUCTION = "introduction", _("Introduction (applicant ↔ interviewer)")
        INTERVIEW_REMINDER = "interview_reminder", _("Interview reminder (to interviewer)")
        DECISION_ACCEPT = "decision_accept", _("Decision — accepted")
        DECISION_REJECT = "decision_reject", _("Decision — not accepted")

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


class AdmissionsSettings(models.Model):
    """Singleton: the Applications Coordinator's workflow knobs."""

    class Mode(models.TextChoices):
        AUTO = "auto", _("Automatic")
        REVIEW = "review", _("Review first")

    acknowledgment_mode = models.CharField(
        max_length=10,
        choices=Mode.choices,
        default=Mode.AUTO,
        verbose_name="Applicant acknowledgment",
        help_text="Automatic emails the acknowledgment as soon as an application "
        "is submitted; review first holds it for you to send (and personalize) "
        "from the console.",
    )
    invitation_mode = models.CharField(
        max_length=10,
        choices=Mode.choices,
        default=Mode.REVIEW,
        verbose_name="Call for interviewers",
        help_text="Automatic emails available analysts to invite them to "
        "interview as soon as an application arrives; review first waits for "
        "you to press Invite on the application.",
    )

    class Meta:
        verbose_name = "Admissions settings"
        verbose_name_plural = "Admissions settings"

    def __str__(self) -> str:
        return "Admissions settings"

    @classmethod
    def load(cls) -> AdmissionsSettings:
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
