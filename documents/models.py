"""Institutional reference documents — governance, formation, founding, etc.

Distinct from ``works.Work`` (member-contributed intellectual output): a
``Document`` is institutional material managed by staff (bylaws,
formation guidelines, founding texts, cartel-process resources). Most
are public; a few may be members-only.

Two-axis visibility (``listing_visibility`` + ``content_visibility``) lets a
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

from accounts.permissions import is_lsp_member
from core.storage import private_storage


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
    file = models.FileField(
        upload_to="documents/%Y/",
        storage=private_storage,
        blank=True,
        help_text=(
            "The source PDF. Optional — leave blank for documents whose "
            "content is authored inline as HTML (the body field below)."
        ),
    )
    body = models.TextField(
        blank=True,
        help_text=(
            "Inline document content (markdown), rendered on the detail page "
            "in place of a PDF. Supports the {{ annual_tuition }} placeholder, "
            "replaced with the current annual tuition figure. Use this for "
            "documents we hold as text rather than a PDF."
        ),
    )
    listing_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text="Who can see this document exists in the index.",
    )
    content_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text=(
            "Who can open the contents — the PDF. Cannot be more public than "
            "the listing — e.g. listing=Members blocks Public contents."
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
            self.content_visibility == self.Visibility.PUBLIC
            and self.listing_visibility == self.Visibility.MEMBERS
        ):
            raise ValidationError({
                "content_visibility": _(
                    "Contents can't be public when the listing is members-only."
                ),
            })
        if not self.file and not self.body:
            raise ValidationError(
                _("A document needs either a PDF file or inline body content.")
            )

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

    @property
    def body_html(self) -> str:
        """The inline body rendered to safe HTML, with site-wide tokens
        (e.g. ``{{ annual_tuition }}``) substituted for the live figure."""
        from .rendering import render_body

        return render_body(self.body)

    def get_absolute_url(self) -> str:
        return reverse("documents:detail", args=[self.slug])

    # ---- Revisions ----

    def snapshot_revision(self, user=None, note: str = "") -> DocumentRevision:
        """Record the state this document is in *now*, before it changes.

        Reads the row back from the database rather than trusting ``self``: a
        ``ModelForm`` mutates its instance in place during validation, which is
        what made ``changed_reviewable_fields()`` silently wrong in #532.
        Re-reading means no caller has to remember to snapshot before binding.
        """
        current = Document.objects.get(pk=self.pk)
        rev = DocumentRevision(document=current, saved_by=user, note=note)
        for name in SNAPSHOT_FIELDS:
            setattr(rev, name, getattr(current, name))
        rev.file = current.file.name or ""
        rev.save()
        return rev

    # ---- Visibility helpers ----

    def listing_visible_to(self, user) -> bool:
        """Whether ``user`` may see this document's listing entry.

        Members-only documents require full LSP membership — an authenticated
        outside registrant (an *auditor*, ``role=external``) is not a member
        and must not see them. Same gate as ``works.Work``.
        """
        if self.listing_visibility == self.Visibility.PUBLIC:
            return True
        return is_lsp_member(user)

    def content_visible_to(self, user) -> bool:
        """Whether ``user`` may open the contents — the PDF (members-only ⇒ LSP
        member)."""
        if self.content_visibility == self.Visibility.PUBLIC:
            return True
        return is_lsp_member(user)

    @classmethod
    def for_user(cls, user):
        """Queryset of *current* documents whose listing is visible to ``user``.

        Excludes superseded versions; use ``Document.supersedes`` on a
        current document to surface its version history.
        """
        qs = cls.objects.filter(superseded_by__isnull=True)
        if is_lsp_member(user):
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


#: The fields a revision snapshots — exactly the set the management form
#: edits, so a restore can write every one of them back.
SNAPSHOT_FIELDS = (
    "title", "summary", "description", "notice", "body", "effective_date",
    "listing_visibility", "content_visibility", "display_order",
)


class DocumentRevision(models.Model):
    """A document's state *before* one save (task #592).

    Each row reads "the document used to be this"; the current state always
    lives on the ``Document``. That ordering means the first edit of an
    already-seeded document captures its original for free, with no synthetic
    baseline row.

    ``file`` holds the storage key the document carried at the time. Django has
    not deleted a replaced ``FileField`` target since 1.3, so the old object is
    still in the bucket and two rows can point at one immutable file. Nothing
    here copies or deletes it.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="revisions",
    )
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    notice = models.CharField(max_length=500, blank=True)
    body = models.TextField(blank=True)
    file = models.FileField(
        upload_to="documents/%Y/", storage=private_storage, blank=True,
    )
    effective_date = models.DateField(null=True, blank=True)
    listing_visibility = models.CharField(max_length=16, blank=True)
    content_visibility = models.CharField(max_length=16, blank=True)
    display_order = models.IntegerField(default=0)
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="document_revisions",
    )
    saved_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-saved_at", "-pk")

    def __str__(self) -> str:
        return f"{self.title} @ {self.saved_at:%Y-%m-%d %H:%M}"

    def changes_against(self, other) -> list[dict]:
        """What changed between this snapshot and ``other`` — the state that
        came after it (the next revision, or the live Document for the newest
        one)."""
        out = []
        for name in SNAPSHOT_FIELDS:
            old, new = getattr(self, name), getattr(other, name)
            if old != new:
                out.append({
                    "field": name,
                    "label": Document._meta.get_field(name).verbose_name,
                    "old": old,
                    "new": new,
                })
        old_file = self.file.name or ""
        new_file = other.file.name or ""
        if old_file != new_file:
            out.append({
                "field": "file", "label": "file",
                "old": old_file, "new": new_file,
            })
        return out
