"""Institutional reference documents — governance, formation, founding, etc.

Distinct from ``works.Work`` (member-contributed intellectual output): a
``Document`` is institutional material managed by staff (bylaws,
formation guidelines, founding texts, cartel-process resources). Most
are public; a few may be members-only.

Two-axis visibility (``listing_visibility`` + ``pdf_visibility``) lets a
document's existence be public while the PDF stays members-only — useful
for founding texts and cartel papers we want to *acknowledge* publicly
while restricting the actual text to members. Same shape as Work.

Documents support version chains via ``superseded_by`` — an older
bylaws PDF stays accessible but points to the current version so the
index only surfaces what's in force.

A document may be *owned* by the group that produced it via
``owning_workgroup`` — a FK to the shared :class:`workgroups.Workgroup`
that committees and working groups both attach. That single relation
expresses "this is a product of the Program Committee" (or any cartel /
working group) without a per-type link, per the add-to-Workgroup-first
principle.
"""

from __future__ import annotations

import markdown
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


class Document(models.Model):
    class Category(models.TextChoices):
        GOVERNANCE = "governance", _("Governance")
        FORMATION = "formation", _("Formation Guidelines")
        FOUNDING = "founding", _("Founding Texts")
        CARTEL_RESOURCE = "cartel_resource", _("Cartel Resources")
        NEWSLETTER = "newsletter", _("Newsletters")
        REFERENCE = "reference", _("Reference")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Public")
        MEMBERS = "members", _("Members only")

    #: Order categories appear in on the index page.
    CATEGORY_ORDER = [
        Category.GOVERNANCE,
        Category.FORMATION,
        Category.FOUNDING,
        Category.CARTEL_RESOURCE,
        Category.NEWSLETTER,
        Category.REFERENCE,
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    category = models.CharField(max_length=32, choices=Category.choices)
    summary = models.CharField(
        max_length=255,
        blank=True,
        help_text="One-line description shown on the index card.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional longer-form description (markdown) for the detail page.",
    )
    notice = models.CharField(
        max_length=500,
        blank=True,
        help_text=(
            "Optional banner shown on the detail page and as a chip on the "
            "index card — e.g. 'Under revision — procedural details may "
            "change'. Leave blank when the document is settled."
        ),
    )
    file = models.FileField(upload_to="documents/%Y/")
    listing_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text="Who can see this document exists in the index.",
    )
    pdf_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text=(
            "Who can download the PDF. Cannot be more public than the "
            "listing — e.g. listing=Members blocks a Public PDF."
        ),
    )
    effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this document took effect (for versioned docs like bylaws).",
    )
    superseded_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supersedes",
        help_text="Set when this document is replaced by a newer version.",
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Sort key within the category. Lower = earlier.",
    )
    authors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="DocumentAuthor",
        related_name="authored_documents",
        blank=True,
    )
    owning_workgroup = models.ForeignKey(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
        help_text=(
            "The committee or working group that produced / owns this "
            "document. Both attach a Workgroup, so this one relation covers "
            "either — e.g. the Program Committee owns its proposal style guide."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "display_order", "title")

    def __str__(self) -> str:
        return self.title

    # ---- Validation ----

    def clean(self):
        if (
            self.pdf_visibility == self.Visibility.PUBLIC
            and self.listing_visibility == self.Visibility.MEMBERS
        ):
            raise ValidationError({
                "pdf_visibility": _(
                    "PDF can't be public when the listing is members-only."
                ),
            })

    # ---- Display helpers ----

    @property
    def is_current(self) -> bool:
        """False when this document has been superseded by a newer version."""
        return self.superseded_by_id is None

    @property
    def description_html(self) -> str:
        if not self.description:
            return ""
        return mark_safe(
            markdown.markdown(
                self.description,
                extensions=["smarty", "sane_lists", "tables"],
                output_format="html5",
            )
        )

    def get_absolute_url(self) -> str:
        return reverse("documents:detail", args=[self.slug])

    # ---- Visibility helpers ----

    def listing_visible_to(self, user) -> bool:
        """Whether ``user`` may see this document's listing entry."""
        if self.listing_visibility == self.Visibility.PUBLIC:
            return True
        return bool(user and user.is_authenticated)

    def pdf_visible_to(self, user) -> bool:
        """Whether ``user`` may download the PDF."""
        if self.pdf_visibility == self.Visibility.PUBLIC:
            return True
        return bool(user and user.is_authenticated)

    @classmethod
    def for_user(cls, user):
        """Queryset of *current* documents whose listing is visible to ``user``.

        Excludes superseded versions; use ``Document.supersedes`` on a
        current document to surface its version history.
        """
        qs = cls.objects.filter(superseded_by__isnull=True)
        if user and user.is_authenticated:
            return qs
        return qs.filter(listing_visibility=cls.Visibility.PUBLIC)


class DocumentAuthor(models.Model):
    """Ordered authorship link between a Document and a User.

    Through model rather than a plain M2M so we can preserve the order
    of authors on the byline. Mirrors ``works.WorkAuthor``.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="authorships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_authorships",
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("display_order",)
        constraints = [
            models.UniqueConstraint(
                fields=("document", "user"),
                name="documents_unique_author_per_document",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} on {self.document}"
