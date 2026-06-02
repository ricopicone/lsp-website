"""Working groups — standing, organization-oriented groups on the shared
Workgroup layer.

Unlike a cartel (formed around a question, time-bounded) or a committee
(policy-setting), a working group is meta — directed at the school's
organizational principles, without policy power. It produces work like a
cartel. Like every group type it *attaches* a :class:`workgroups.Workgroup`,
which holds the roster, channel, works, files, and landing page; ``WorkingGroup``
starts thin and grows only genuinely working-group-specific fields.
"""

from __future__ import annotations

from django.db import models, transaction
from django.utils.text import slugify

from workgroups.models import Workgroup, WorkgroupMembership, build_workgroup


class WorkingGroupManager(models.Manager):
    @transaction.atomic
    def create_with_workgroup(self, *, name, **workgroup_kwargs):
        wg = build_workgroup(Workgroup.Kind.WORKING_GROUP, name=name, **workgroup_kwargs)
        return self.create(workgroup=wg)

    @transaction.atomic
    def create_with_chair(self, *, name, chair, members=(), **workgroup_kwargs):
        """Board-gated creation (G3): build a standing working group, seed its
        chair (``role=CHAIR``) and any initial members. No approval step — it's
        published (landing visible to members) on creation.

        ``build_workgroup``/``Workgroup.save`` don't uniquify the unique slug,
        so de-dup here (mirrors ``committees.Committee.save``) to avoid an
        IntegrityError on a duplicate name."""
        if "slug" not in workgroup_kwargs:
            base = slugify(name)[:140] or "working-group"
            slug, n = base, 2
            while Workgroup.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            workgroup_kwargs["slug"] = slug
        wg = build_workgroup(Workgroup.Kind.WORKING_GROUP, name=name, **workgroup_kwargs)
        working_group = self.create(workgroup=wg)
        wg._add_member(chair, role=WorkgroupMembership.Role.CHAIR)
        for member in members:
            if member != chair:
                wg._add_member(member)
        return working_group


class WorkingGroup(models.Model):
    workgroup = models.OneToOneField(
        Workgroup,
        on_delete=models.CASCADE,
        related_name="working_group",
    )

    objects = WorkingGroupManager()

    def __str__(self) -> str:
        return self.workgroup.name

    def get_absolute_url(self) -> str:
        return self.workgroup.get_absolute_url()
