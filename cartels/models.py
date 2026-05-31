"""Cartels — the first concrete group type on the shared Workgroup layer.

A cartel *attaches* a :class:`workgroups.Workgroup` (which holds the roster,
channel, works, files, and landing page). ``Cartel`` itself starts thin and
carries only cartel-specific extras as they arrive (CART-4 formation workflow,
the guiding question / trait, the cartel "product" link). The Lacanian
plus-one is not a field here — it's a ``WorkgroupMembership`` with
``role=PLUS_ONE``.
"""

from __future__ import annotations

from django.db import models, transaction

from workgroups.models import Workgroup, build_workgroup


class CartelManager(models.Manager):
    @transaction.atomic
    def create_with_workgroup(self, *, name, **workgroup_kwargs):
        """Create a Cartel and its backing Workgroup in one step.

        Applies the cartel capability-toggle seed; any explicit toggle passed
        in ``workgroup_kwargs`` wins.
        """
        wg = build_workgroup(Workgroup.Kind.CARTEL, name=name, **workgroup_kwargs)
        return self.create(workgroup=wg)


class Cartel(models.Model):
    workgroup = models.OneToOneField(
        Workgroup,
        on_delete=models.CASCADE,
        related_name="cartel",
    )

    objects = CartelManager()

    def __str__(self) -> str:
        return self.workgroup.name

    def get_absolute_url(self) -> str:
        return self.workgroup.get_absolute_url()
