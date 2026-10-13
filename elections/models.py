"""Board elections (task #813).

See docs/superpowers/specs/2026-10-12-board-elections-design.md. The phase is
computed from dates and step stamps, never stored, so it cannot drift from
them. Ballot rankings are read ONLY through ``elections.ballots``.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Election(models.Model):
    class Phase(models.TextChoices):
        DRAFT = "draft", "Draft"
        NOMINATING = "nominating", "Nominations open"
        REVIEW = "review", "Board review"
        SLATE = "slate", "Slate published"
        VOTING = "voting", "Voting open"
        CLOSED = "closed", "Voting closed"
        COUNTED = "counted", "Counted"
        PUBLISHED = "published", "Results published"
        ACCLAIMED = "acclaimed", "Elected without a vote"

    class CountMethod(models.TextChoices):
        STV = "stv", "Single transferable vote (STV)"
        TOP_N = "top_n", "Most votes (each ballot's top choices)"

    class DuringVoting(models.TextChoices):
        STATUS = "status", "Status only"
        TURNOUT = "turnout", "Status and turnout"

    class ResultsShown(models.TextChoices):
        WINNERS = "winners", "Winners only"
        FULL = "full", "Winners and the full count"

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    seats = models.PositiveSmallIntegerField(default=1)
    nominations_open_at = models.DateTimeField()
    nominations_close_at = models.DateTimeField()
    voting_open_at = models.DateTimeField()
    voting_close_at = models.DateTimeField()
    results_due = models.DateField(null=True, blank=True)
    count_method = models.CharField(
        max_length=10, choices=CountMethod.choices, default=CountMethod.STV,
    )
    show_during_voting = models.CharField(
        max_length=10, choices=DuringVoting.choices, default=DuringVoting.STATUS,
    )
    show_results = models.CharField(
        max_length=10, choices=ResultsShown.choices, default=ResultsShown.WINNERS,
    )

    call_sent_at = models.DateTimeField(null=True, blank=True)
    slate_published_at = models.DateTimeField(null=True, blank=True)
    slate_published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    roll_frozen_at = models.DateTimeField(null=True, blank=True)
    voting_notice_sent_at = models.DateTimeField(null=True, blank=True)
    counted_at = models.DateTimeField(null=True, blank=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    results_published_at = models.DateTimeField(null=True, blank=True)
    results_published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    acclaimed_at = models.DateTimeField(null=True, blank=True)
    acclaimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    count_result = models.JSONField(null=True, blank=True)
    audit_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-nominations_open_at",)

    FINAL_PHASES = frozenset({Phase.PUBLISHED, Phase.ACCLAIMED})

    def __str__(self) -> str:
        return self.title

    def phase_at(self, now) -> str:
        P = self.Phase
        if self.acclaimed_at:
            return P.ACCLAIMED
        if self.results_published_at:
            return P.PUBLISHED
        if self.counted_at:
            return P.COUNTED
        if now < self.nominations_open_at:
            return P.DRAFT
        if now < self.nominations_close_at:
            return P.NOMINATING
        # Voting never opens before the slate is published, whatever the date.
        if self.slate_published_at is None:
            return P.REVIEW
        if now < self.voting_open_at:
            return P.SLATE
        if now < self.voting_close_at:
            return P.VOTING
        return P.CLOSED

    @property
    def phase(self) -> str:
        return self.phase_at(timezone.now())

    def get_phase_display(self) -> str:
        return self.Phase(self.phase).label

    def append_audit(self, by, text: str) -> None:
        """Append one ``[date] who: what`` line. Does not save."""
        who = (by.get_full_name() or by.email) if by is not None else "site"
        line = f"[{timezone.localtime():%Y-%m-%d %H:%M}] {who}: {text}"
        self.audit_notes = f"{self.audit_notes}\n{line}".strip()


class Nomination(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Under review"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Not accepted"

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name="nominations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="election_nominations",
    )
    letter = models.TextField()
    role_at_submission = models.CharField(max_length=32, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    board_note = models.TextField(blank=True)

    class Meta:
        ordering = ("user__last_name", "user__first_name")
        constraints = [
            models.UniqueConstraint(
                fields=["election", "user"],
                name="election_one_nomination_per_member",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}: {self.election}"

    @property
    def is_live(self) -> bool:
        return self.withdrawn_at is None

    @property
    def name(self) -> str:
        return self.user.get_full_name() or self.user.email


class VoterRollEntry(models.Model):
    """One row per person the administrator has touched or who is on the
    frozen roll. Before the freeze only override rows exist; at the freeze
    every voter gets ``on_roll=True``."""

    class Override(models.TextChoices):
        NONE = "", "None"
        ADD = "add", "Added by the administrator"
        REMOVE = "remove", "Removed by the administrator"

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name="roll",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="election_roll_entries",
    )
    override = models.CharField(
        max_length=10, choices=Override.choices, blank=True, default="",
    )
    reason = models.CharField(max_length=300, blank=True)
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    override_at = models.DateTimeField(null=True, blank=True)
    on_roll = models.BooleanField(default=False)
    role_at_freeze = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name_plural = "voter roll entries"
        constraints = [
            models.UniqueConstraint(
                fields=["election", "user"],
                name="election_one_roll_row_per_member",
            ),
        ]


class Ballot(models.Model):
    """Linked to its voter; the link is shown to nobody but the voter.
    Read rankings ONLY through ``elections.ballots``."""

    election = models.ForeignKey(
        Election, on_delete=models.CASCADE, related_name="ballots",
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="election_ballots",
    )
    cast_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["election", "voter"],
                name="election_one_ballot_per_voter",
            ),
        ]


class BallotRanking(models.Model):
    ballot = models.ForeignKey(
        Ballot, on_delete=models.CASCADE, related_name="rankings",
    )
    nomination = models.ForeignKey(
        Nomination, on_delete=models.CASCADE, related_name="+",
    )
    rank = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ballot", "rank"], name="ballot_rank_unique",
            ),
            models.UniqueConstraint(
                fields=["ballot", "nomination"], name="ballot_candidate_unique",
            ),
        ]
