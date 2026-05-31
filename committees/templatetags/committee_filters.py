"""Template filters for committee membership checks."""

from django import template

from workgroups.models import WorkgroupMembership

register = template.Library()


@register.filter
def is_on_committee(user, slug: str) -> bool:
    """True if ``user`` is a current member of the committee with ``slug``.

    Reads the unified roster via the committee's attached workgroup.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return WorkgroupMembership.objects.filter(
        user=user, end_date__isnull=True, workgroup__committee__slug=slug,
    ).exists()
