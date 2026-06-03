"""Committee membership checks (read via the unified workgroup roster)."""

from __future__ import annotations

from workgroups.models import WorkgroupMembership


def is_on_committee(user, slug: str) -> bool:
    """True if ``user`` is a current member of the committee with ``slug``."""
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.serving().filter(
        user=user, workgroup__committee__slug=slug,
    ).exists()
