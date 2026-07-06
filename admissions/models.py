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
