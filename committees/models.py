"""LSP committees and memberships (USR-7).

A ``Committee`` is an organizational entity with its own page, charter, and
roster. ``CommitteeMembership`` records a user's tenure on a committee,
including the role they hold within it and their term dates. Multiple
historical memberships per (user, committee) are allowed; at most one
*active* (``end_date IS NULL``) membership per pair is enforced via a
partial unique constraint.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Committee(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text="One-line summary for listings.",
    )
    charter = models.TextField(
        blank=True,
        help_text="Longer-form description of what this committee does.",
    )
    public = models.BooleanField(
        default=False,
        help_text="Whether this committee has a public page.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def active_members(self):
        return self.memberships.filter(end_date__isnull=True).select_related("user")


class CommitteeMembership(models.Model):
    class Role(models.TextChoices):
        MEMBER = "member", _("Member")
        CHAIR = "chair", _("Chair")
        CO_CHAIR = "co_chair", _("Co-chair")
        SECRETARY = "secretary", _("Secretary")
        TREASURER = "treasurer", _("Treasurer")
        # Staff positions
        REFERRAL_COORDINATOR = "referral_coordinator", _("Referral Coordinator")
        WEB_COORDINATOR = "web_coordinator", _("Web Coordinator")
        ADMIN_ASSISTANT = "admin_assistant", _("Admin Assistant")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="committee_memberships",
    )
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role_in_committee = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    start_date = models.DateField()
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Null for currently-serving members.",
    )

    class Meta:
        ordering = ("committee__name", "-start_date")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "committee"),
                condition=models.Q(end_date__isnull=True),
                name="committees_one_active_membership_per_user_committee",
            ),
        ]

    def __str__(self):
        active = "active" if self.end_date is None else f"ended {self.end_date.isoformat()}"
        return f"{self.user} — {self.committee} ({self.get_role_in_committee_display()}, {active})"

    @property
    def is_active(self) -> bool:
        return self.end_date is None
