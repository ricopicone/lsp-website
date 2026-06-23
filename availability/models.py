"""Analyst availability — which analysts are available for which LSP functions.

The school's Applications Coordinator circulates a yearly table of which
Analysts are available for **Application Interviews**, to serve as an
**Advisor**, for **Control analysis** (supervision), and for **Personal
analysis** (see the "LSP Analysts Availability" PDF). This app turns that
table into per-analyst data woven into the directory.

Two models carry it:

- :class:`AnalystFunction` — the columns (admin-editable, so the school can
  add or rename functions without a code change).
- :class:`AvailabilitySpan` — the source of truth, an **interval log**. Each
  span records a tri-state status (Yes / No / Unknown — matching the PDF
  legend) for one analyst × one function over a date range. The *open* span
  (``end_date`` is null) is the current state; turning availability on/off
  closes the open span and opens a new one. Because every span carries who
  set it, when, and from where, the table is also the audit trail — and because
  spans are dated intervals we can compute what fraction of an academic year an
  analyst held a given function ("credit"; see ``services.coverage_fraction``).

Per the do-not-over-automate principle, nothing here writes itself: the
import, the coordinator console, and member self-service all flow through
``services.set_availability`` and a staff override is always available.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AnalystFunction(models.Model):
    """An LSP function an analyst may be available for (a table column).

    Seeded with the four functions on the Applications Coordinator's sheet —
    Application Interviews, Advisor, Control analysis, Personal analysis — but
    editable so the school can add, rename, reorder, or retire functions
    without a migration. Retire by clearing ``is_active`` rather than deleting,
    so historical :class:`AvailabilitySpan` rows are preserved.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="The function's full name, used as the table column header "
        "(e.g. 'Application Interviews').",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL-safe key; used in linkable directory filters "
        "(?function=application-interviews).",
    )
    short_label = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optional compact header for narrow table columns. "
        "Falls back to the name when blank.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional explanation shown to members alongside the function.",
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers sort first in the table and filters.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive functions are hidden from members and the console "
        "but keep their history.",
    )

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def column_label(self) -> str:
        """The header to render — the short label if set, else the full name."""
        return self.short_label or self.name


class AvailabilitySpan(models.Model):
    """One analyst's status for one function over a date interval.

    The *open* span (``end_date is None``) is the current state. ``services``
    maintains the invariant of at most one open span per (profile, function);
    a DB constraint backs it up. Do not create or close spans by hand — go
    through ``services.set_availability`` so transitions stay consistent.
    """

    class Status(models.TextChoices):
        YES = "yes", _("Yes")
        NO = "no", _("No")
        UNKNOWN = "unknown", _("Unknown")

    class Source(models.TextChoices):
        """Where a span came from — for the audit trail."""

        IMPORT = "import", _("Imported from the yearly sheet")
        COORDINATOR = "coordinator", _("Set by the Applications Coordinator")
        SELF = "self", _("Set by the analyst")
        ADMIN = "admin", _("Set in the Django admin")

    profile = models.ForeignKey(
        "accounts.Profile",
        on_delete=models.CASCADE,
        related_name="availability_spans",
    )
    function = models.ForeignKey(
        AnalystFunction,
        on_delete=models.PROTECT,
        related_name="spans",
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.UNKNOWN,
    )
    start_date = models.DateField(
        help_text="The day this status took effect.",
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="The day this status ended. Null means it is the current "
        "status (the open span).",
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        help_text="Function-specific qualifier, verbatim from the sheet where "
        "given (e.g. 'Interviews OK Sept 2026', 'Except Oct-Dec 2026').",
    )
    source = models.CharField(
        max_length=12,
        choices=Source.choices,
        default=Source.ADMIN,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who recorded this span (null for an import or system action).",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["profile", "function", "-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "function"],
                condition=models.Q(end_date__isnull=True),
                name="availability_one_open_span_per_profile_function",
            ),
        ]
        indexes = [
            models.Index(fields=["function", "status", "end_date"]),
        ]

    def __str__(self) -> str:
        end = self.end_date.isoformat() if self.end_date else "present"
        return f"{self.profile_id} · {self.function_id}: {self.status} ({self.start_date}–{end})"

    @property
    def is_open(self) -> bool:
        """Whether this span is the current state (no end date)."""
        return self.end_date is None
