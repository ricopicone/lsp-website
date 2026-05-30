"""Catalog of member intellectual output — external publications, cartel
work, Palimpsest essays, Passage essays.

Distinct from ``documents.Document`` (institutional reference material
managed by staff): ``Work`` entries are member-contributed and have a
two-axis visibility model so a member can list their journal article
publicly while keeping the PDF (which they don't own publisher rights
to) restricted to LSP members.

Cartel-internal visibility (only cartel members see the work) is
deferred to M14 — for now the CARTEL kind uses the same PUBLIC/MEMBERS
visibility as everything else.
"""

from __future__ import annotations

import markdown
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class Work(models.Model):
    class Kind(models.TextChoices):
        EXTERNAL   = "external",   _("External publication")
        CARTEL     = "cartel",     _("Cartel work")
        PALIMPSEST = "palimpsest", _("Palimpsest")
        PASSAGE    = "passage",    _("Passage")

    class Visibility(models.TextChoices):
        PUBLIC  = "public",  _("Public")
        MEMBERS = "members", _("Members only")

    class PDFVisibility(models.TextChoices):
        # NONE = no PDF was uploaded. Modelled as a visibility value (vs a
        # nullable separate field) so the catalog filters can express
        # "works with a PDF I can read" uniformly.
        NONE    = "none",    _("No PDF")
        PUBLIC  = "public",  _("Public PDF")
        MEMBERS = "members", _("Members-only PDF")

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)

    listing_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text="Who can see this work exists in the catalog.",
    )
    pdf_visibility = models.CharField(
        max_length=16,
        choices=PDFVisibility.choices,
        default=PDFVisibility.NONE,
        help_text=(
            "Who can download the PDF. Cannot be more public than the "
            "listing — e.g. listing=Members blocks a Public PDF."
        ),
    )

    abstract = models.TextField(
        blank=True,
        help_text="Short summary (markdown supported).",
    )
    publication_info = models.CharField(
        max_length=255,
        blank=True,
        help_text='Free-form citation, e.g. "Journal of X, Vol 12 (2024), pp. 33–58".',
    )
    url = models.URLField(
        blank=True,
        help_text="Link to publisher / DOI / external page.",
    )
    publication_date = models.DateField(null=True, blank=True)

    pdf = models.FileField(
        upload_to="works/pdf/%Y/",
        blank=True,
        null=True,
    )
    cover_image = models.ImageField(
        upload_to="works/covers/%Y/",
        blank=True,
        null=True,
    )

    external_authors = models.CharField(
        max_length=255,
        blank=True,
        help_text="Free-text co-authors not in our system (comma-separated).",
    )

    authors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="WorkAuthor",
        related_name="authored_works",
        blank=True,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_works",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-publication_date", "-created_at")

    def __str__(self) -> str:
        return self.title

    # ---- Validation ----

    def clean(self):
        # PDF visibility cannot be more open than listing visibility.
        if (
            self.pdf_visibility == self.PDFVisibility.PUBLIC
            and self.listing_visibility == self.Visibility.MEMBERS
        ):
            raise ValidationError({
                "pdf_visibility": _(
                    "PDF can't be public when the listing is members-only."
                ),
            })
        # PDF visibility says there's a PDF; ensure one is actually attached.
        if self.pdf_visibility != self.PDFVisibility.NONE and not self.pdf:
            raise ValidationError({
                "pdf": _("Attach a PDF or set PDF visibility to 'No PDF'."),
            })
        # Conversely: an attached PDF needs a real visibility.
        if self.pdf and self.pdf_visibility == self.PDFVisibility.NONE:
            raise ValidationError({
                "pdf_visibility": _("Pick a visibility for the attached PDF."),
            })

    # ---- Visibility helpers ----

    def listing_visible_to(self, user) -> bool:
        if self.listing_visibility == self.Visibility.PUBLIC:
            return True
        return bool(user and user.is_authenticated)

    def pdf_visible_to(self, user) -> bool:
        if self.pdf_visibility == self.PDFVisibility.NONE or not self.pdf:
            return False
        if self.pdf_visibility == self.PDFVisibility.PUBLIC:
            return True
        return bool(user and user.is_authenticated)

    @classmethod
    def listing_for(cls, user):
        """Queryset of works whose *listing* is visible to ``user``."""
        if user and user.is_authenticated:
            return cls.objects.all()
        return cls.objects.filter(listing_visibility=cls.Visibility.PUBLIC)

    # ---- Edit permission ----

    def editable_by(self, user) -> bool:
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        if self.submitted_by_id == user.id:
            return True
        return self.authors.filter(pk=user.pk).exists()

    # ---- Display helpers ----

    @property
    def abstract_html(self) -> str:
        if not self.abstract:
            return ""
        return mark_safe(markdown.markdown(
            self.abstract,
            extensions=["smarty", "sane_lists"],
            output_format="html5",
        ))

    def get_absolute_url(self) -> str:
        return reverse("works:detail", args=[self.slug])

    def author_display(self) -> str:
        """Plain-text "Last, First; Last, First; External Name" string."""
        from accounts.models import User
        names = [
            (wa.user.last_name or "") + (", " + wa.user.first_name if wa.user.first_name else "")
            for wa in (
                WorkAuthor.objects
                .filter(work=self)
                .select_related("user")
                .order_by("display_order")
            )
            if isinstance(wa.user, User)
        ]
        if self.external_authors:
            names.append(self.external_authors)
        return "; ".join(n for n in names if n)


class WorkAuthor(models.Model):
    """Ordered authorship link between a Work and a User.

    Through model rather than a plain M2M so we can preserve the order
    of authors on the byline.
    """

    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="authorships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authorships",
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("display_order",)
        constraints = [
            models.UniqueConstraint(
                fields=("work", "user"),
                name="works_unique_author_per_work",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} on {self.work}"
