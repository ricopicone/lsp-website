"""Template filters for committee membership checks."""

from django import template

from committees.models import CommitteeMembership

register = template.Library()


@register.filter
def is_on_committee(user, slug: str) -> bool:
    """True if ``user`` is a current member of the committee with ``slug``."""
    if not getattr(user, "is_authenticated", False):
        return False
    return CommitteeMembership.objects.filter(
        user=user, committee__slug=slug, end_date__isnull=True,
    ).exists()
