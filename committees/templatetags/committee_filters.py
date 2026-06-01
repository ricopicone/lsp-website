"""Template filters for committee membership checks."""

from django import template

from committees.permissions import is_on_committee as _is_on_committee

register = template.Library()


@register.filter
def is_on_committee(user, slug: str) -> bool:
    """True if ``user`` is a current member of the committee with ``slug``.

    Reads the unified roster via the committee's attached workgroup.
    """
    return _is_on_committee(user, slug)
