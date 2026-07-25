from django import template

from works.citation import source_html

register = template.Library()


@register.filter
def work_source_line(work):
    """The Chicago venue line (no authors/title) for list rows and cards."""
    return source_html(work)
