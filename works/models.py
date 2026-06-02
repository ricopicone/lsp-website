"""Catalog of member intellectual output — external publications, cartel
work, Palimpsest essays, Passage essays.

Distinct from ``documents.Document`` (institutional reference material
managed by staff): ``Work`` entries are member-contributed and have a
two-axis visibility model so a member can list their journal article
publicly while keeping the PDF (which they don't own publisher rights
to) restricted to LSP members.

A Work has zero or more ``WorkFile`` rows. A single file renders as
one download button; multiple files render as a labeled list and each
file must carry a label.

Visibility levels (most → least public): PUBLIC (anyone), MEMBERS (any LSP
member — see ``accounts.permissions.is_lsp_member``), GROUP (members of the
producing workgroup only). "Members only" means an actual member of the
school, consistent with ``workgroups.Workgroup`` — not merely a logged-in
account (prospective applicants, students, and guests don't qualify).
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


class Work(models.Model):
    class Kind(models.TextChoices):
        EXTERNAL   = "external",   _("External publication")
        CARTEL     = "cartel",     _("Cartel work")
        PALIMPSEST = "palimpsest", _("Palimpsest")
        PASSAGE    = "passage",    _("Passage")
        DOCUMENT   = "document",   _("Document")

    class Visibility(models.TextChoices):
        PUBLIC  = "public",  _("Public")
        MEMBERS = "members", _("Members only")
        GROUP   = "group",   _("Workgroup members only")

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)

    workgroup = models.ForeignKey(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="works",
        help_text="The producing group. Required when a visibility is set to "
        "'Workgroup members only'.",
    )
    in_progress = models.BooleanField(
        default=False,
        help_text="Still being worked on (vs. released). Shown separately on the "
        "group's Work tab.",
    )

    listing_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        help_text="Who can see this work exists in the catalog.",
    )
    pdf_visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.MEMBERS,
        help_text=(
            "Who can download the PDFs attached to this work. Cannot be "
            "more public than the listing — listing=Members blocks a "
            "Public PDF setting."
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

    cover_image = models.ImageField(
        upload_to="works/covers/%Y/",
        blank=True,
        null=True,
    )
    #: Published web version (rendered HTML) when this Work was produced by
    #: publishing a WorkDraft. Shown on the Work page; the generated PDF is
    #: attached as a WorkFile (so existing download + visibility apply).
    body_html = models.TextField(blank=True)

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

    #: Publicness rank — higher = more open. GROUP (one group's members) is
    #: the most restrictive, below MEMBERS (any logged-in member).
    _VISIBILITY_RANK = {
        Visibility.PUBLIC: 2,
        Visibility.MEMBERS: 1,
        Visibility.GROUP: 0,
    }

    def clean(self):
        rank = self._VISIBILITY_RANK
        if rank[self.pdf_visibility] > rank[self.listing_visibility]:
            raise ValidationError({
                "pdf_visibility": _(
                    "The PDF can't be more public than the listing."
                ),
            })
        if (
            self.Visibility.GROUP in (self.listing_visibility, self.pdf_visibility)
            and self.workgroup_id is None
        ):
            raise ValidationError({
                "workgroup": _(
                    "Set a workgroup when visibility is 'Workgroup members only'."
                ),
            })

    # ---- Visibility helpers ----

    def _visible_at(self, level, user) -> bool:
        if level == self.Visibility.PUBLIC:
            return True
        if level == self.Visibility.GROUP:
            # Active members + past-term attendees (read-only archive) of the
            # producing workgroup.
            return bool(self.workgroup_id and (
                self.workgroup.is_member(user)
                or self.workgroup.has_archive_access(user)
            ))
        return is_lsp_member(user)  # MEMBERS — an actual LSP member, not just logged in

    def listing_visible_to(self, user) -> bool:
        return self._visible_at(self.listing_visibility, user)

    def pdf_visible_to(self, user) -> bool:
        """True only when (a) visibility permits and (b) at least one file exists."""
        if not self.files.exists():
            return False
        return self._visible_at(self.pdf_visibility, user)

    @classmethod
    def listing_for(cls, user):
        """Queryset of works whose *listing* is visible to ``user``.

        GROUP-visibility works are shown only to members of the producing
        workgroup — no staff bypass (cartel-internal output is genuinely
        group-only; admins still see everything via the Django admin).
        """
        from django.db.models import Q

        visible = Q(listing_visibility=cls.Visibility.PUBLIC)
        if not (user and user.is_authenticated):
            return cls.objects.filter(visible)

        if is_lsp_member(user):
            visible |= Q(listing_visibility=cls.Visibility.MEMBERS)

        from workgroups.models import WorkgroupMembership

        member_group_ids = WorkgroupMembership.objects.filter(
            user=user, end_date__isnull=True
        ).values("workgroup_id")
        visible |= Q(
            listing_visibility=cls.Visibility.GROUP, workgroup_id__in=member_group_ids
        )
        return cls.objects.filter(visible)

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


class WorkFile(models.Model):
    """A PDF (or other) file attached to a Work.

    A Work with one file renders as a single download button; with
    multiple, the detail page renders a labeled list and the form
    requires every file to carry a non-empty label.
    """

    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="works/files/%Y/")
    label = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "Optional when this is the work's only file; required when "
            "the work has multiple files."
        ),
    )
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("display_order", "created_at")

    def __str__(self) -> str:
        return self.label or self.file.name.rsplit("/", 1)[-1]


class WorkDraft(models.Model):
    """A collaborative working document in a workgroup's Work tab — drafted
    in-browser (TipTap, autosaved, versioned) and eventually *published* into a
    :class:`Work` (web page + PDF). Either native (``content_html``) or a link
    to an external Google Doc (``google_doc_url``)."""

    workgroup = models.ForeignKey(
        "workgroups.Workgroup", on_delete=models.CASCADE, related_name="drafts"
    )
    title = models.CharField(max_length=200, default="Untitled document")
    content_html = models.TextField(blank=True)
    google_doc_url = models.URLField(
        blank=True, help_text="If set, this is a linked Google Doc (no in-app editing)."
    )
    #: Soft, advisory edit lock — who's currently editing + when last seen.
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locked_drafts",
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    published_work = models.OneToOneField(
        "works.Work", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="source_draft",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_drafts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="edited_drafts",
    )

    #: A held lock is considered active for this long since the last heartbeat.
    LOCK_TTL_SECONDS = 180

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("workgroups:draft_edit", args=[self.workgroup.slug, self.pk])

    @property
    def is_linked(self) -> bool:
        return bool(self.google_doc_url)

    def active_lock_holder(self):
        """The user currently holding a live edit lock, or None (stale/unlocked)."""
        from datetime import timedelta

        from django.utils import timezone
        if self.locked_by_id is None or self.locked_at is None:
            return None
        if timezone.now() - self.locked_at > timedelta(seconds=self.LOCK_TTL_SECONDS):
            return None
        return self.locked_by

    def can_edit_now(self, user) -> bool:
        """True if ``user`` may write (lock free / stale / theirs)."""
        holder = self.active_lock_holder()
        return holder is None or holder.pk == user.pk

    def acquire_lock(self, user):
        from django.utils import timezone
        self.locked_by = user
        self.locked_at = timezone.now()
        self.save(update_fields=["locked_by", "locked_at"])


class WorkDraftVersion(models.Model):
    """A named snapshot of a draft's content (manual save-version + on publish)."""

    draft = models.ForeignKey(
        WorkDraft, on_delete=models.CASCADE, related_name="versions"
    )
    content_html = models.TextField(blank=True)
    label = models.CharField(max_length=120, blank=True)
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="saved_draft_versions",
    )
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-saved_at",)

    def __str__(self) -> str:
        return f"{self.draft.title} @ {self.saved_at:%Y-%m-%d %H:%M}"
