"""The member suggestion box.

Any signed-in member can file a :class:`Suggestion` — a typo, a bug, a content
fix, a feature idea — ideally anchored to the page they were looking at. A
suggestion is **private**: visible only to its submitter and to site staff
(Web Coordinator / Web Developer). Staff triage it from
``/admin-tools/suggestions/`` and can export a batch as structured markdown
briefs (:mod:`suggestions.export`) that a Claude Code session works through.

The model mirrors ``events.EventProposal``'s shape: a typed status workflow, a
submitter FK that survives the user being deleted, and review bookkeeping.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.storage import private_storage


class Suggestion(models.Model):
    class Kind(models.TextChoices):
        BUG = "bug", _("Something's broken")
        CONTENT = "content", _("Wording / typo / content")
        FEATURE = "feature", _("New feature or idea")
        DESIGN = "design", _("Design / layout")
        OTHER = "other", _("Something else")

    class Status(models.TextChoices):
        NEW = "new", _("New")
        ACKNOWLEDGED = "acknowledged", _("Acknowledged")
        PLANNED = "planned", _("Planned")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")
        DECLINED = "declined", _("Declined")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")

    #: Statuses worth exporting to a Claude Code brief by default (not done /
    #: declined).
    ACTIONABLE_STATUSES = (
        Status.NEW,
        Status.ACKNOWLEDGED,
        Status.PLANNED,
        Status.IN_PROGRESS,
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="suggestions",
    )
    kind = models.CharField(
        max_length=12, choices=Kind.choices, default=Kind.OTHER,
        help_text="What kind of change you're suggesting.",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(
        blank=True,
        help_text="What you'd change, and (for a bug) what you expected instead.",
    )
    #: The page the suggestion is about — a site-relative path (e.g. "/directory/"),
    #: captured by the floating widget. Blank for the standalone form.
    page_url = models.CharField(max_length=500, blank=True)
    page_title = models.CharField(max_length=300, blank=True)
    #: Optional browser context (user-agent, viewport, referrer) the widget
    #: collects — handy when triaging a bug.
    context = models.JSONField(default=dict, blank=True)
    screenshot = models.ImageField(
        upload_to="suggestions/", storage=private_storage, null=True, blank=True,
        help_text="Optional screenshot (private — submitter and staff only).",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NEW,
    )
    priority = models.CharField(
        max_length=8, choices=Priority.choices, blank=True,
    )
    staff_notes = models.TextField(
        blank=True, help_text="Triage notes (staff-only; not shown to the submitter).",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="suggestions_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    #: Stamped when the suggestion is written into a Claude Code brief; drives the
    #: ``--unexported`` export filter.
    exported_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.title} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.ACTIONABLE_STATUSES
