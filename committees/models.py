"""LSP committees (USR-7).

A ``Committee`` is an organizational entity with its own page and charter. As
of the Stage-4 workgroups fold-in it *attaches* a :class:`workgroups.Workgroup`
(``kind=committee``) which holds the roster — membership lives on
``workgroups.WorkgroupMembership``, not here. ``Committee`` keeps only its
committee-specific identity (charter, public page). See
``docs/design-workgroups.md``.
"""

from __future__ import annotations

from django.db import models


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
    workgroup = models.OneToOneField(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="committee",
        help_text="The backing workgroup (kind=committee) that holds the roster.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Ensure every committee has a backing committee-kind workgroup.

        The Stage-4 fold-in migration backfills existing committees; this keeps
        the invariant for any committee created afterward (admin, seed, tests).
        """
        super().save(*args, **kwargs)
        if self.workgroup_id is None:
            from workgroups.models import Workgroup, build_workgroup

            slug, n = self.slug, 2
            while Workgroup.objects.filter(slug=slug).exists():
                slug = f"{self.slug}-{n}"
                n += 1
            self.workgroup = build_workgroup(
                Workgroup.Kind.COMMITTEE,
                name=self.name,
                slug=slug,
                description=self.description or "",
                landing_visibility="public" if self.public else "members",
                content_visibility="members",
            )
            super().save(update_fields=["workgroup"])

    def active_members(self):
        """Current roster, read from the attached workgroup."""
        if self.workgroup_id is None:
            from workgroups.models import WorkgroupMembership

            return WorkgroupMembership.objects.none()
        return self.workgroup.active_members()

    def add_member(self, user, *, role="member", start_date=None, end_date=None):
        """Add ``user`` to this committee's roster (on its workgroup)."""
        from workgroups.models import WorkgroupMembership

        if start_date is None:
            start_date = self.created_at.date() if self.created_at else None
        return WorkgroupMembership.objects.create(
            workgroup=self.workgroup,
            user=user,
            role=role,
            start_date=start_date,
            end_date=end_date,
        )
