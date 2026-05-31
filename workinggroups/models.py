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

from workgroups.models import Workgroup, build_workgroup


class WorkingGroupManager(models.Manager):
    @transaction.atomic
    def create_with_workgroup(self, *, name, **workgroup_kwargs):
        wg = build_workgroup(Workgroup.Kind.WORKING_GROUP, name=name, **workgroup_kwargs)
        return self.create(workgroup=wg)


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
