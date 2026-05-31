"""Template helpers for Parlêtre (nav gating + inline SVG icons)."""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from parletre.permissions import is_member

register = template.Library()


@register.filter(name="is_parletre_member")
def is_parletre_member(user) -> bool:
    """True if ``user`` may enter Parlêtre (drives the nav link)."""
    return is_member(user)


# --- inline SVG icons ----------------------------------------------------
#
# Decorative glyphs (lock, hourglass, pin, …) used to be emoji, which render
# inconsistently across platforms and can't be themed. These are minimal
# stroke icons (Feather/Lucide idiom, 24×24, stroke=currentColor) so they
# inherit text colour and scale with font-size (width/height = 1em). Drawing
# them inline — rather than as CSS background-images or JS-built <svg> — keeps
# them out of Tailwind's class-scan blind spot and lets them be sized with a
# plain class. Add new glyphs here, reference with {% icon "name" %}.

_ICON_PATHS = {
    # locked / private
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    # disappearing / ephemeral
    "hourglass": (
        '<path d="M6 2h12M6 22h12"/>'
        '<path d="M6 2c0 4 4 6 6 10 2-4 6-6 6-10"/>'
        '<path d="M6 22c0-4 4-6 6-10 2 4 6 6 6 10"/>'
    ),
    # pinned
    "pin": (
        '<path d="M12 17v5"/>'
        '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6z"/>'
    ),
    # posted by email
    "mail": (
        '<rect x="3" y="5" width="18" height="14" rx="2"/>'
        '<path d="m3 7 9 6 9-6"/>'
    ),
    # attachment
    "paperclip": (
        '<path d="M21 8.5 12.5 17a4 4 0 0 1-5.66-5.66l8.49-8.48a2.5 2.5 0 0 1 '
        '3.54 3.54l-8.5 8.49a1 1 0 0 1-1.41-1.42l7.78-7.77"/>'
    ),
    # send (up arrow)
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    # jump to unread (down arrow)
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    # reply / in-reply-to
    "reply": '<path d="M9 17 4 12l5-5"/><path d="M4 12h11a5 5 0 0 1 5 5v1"/>',
    # cancel / close
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    # notifications bell
    "bell": (
        '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>'
        '<path d="M13.7 21a2 2 0 0 1-3.4 0"/>'
    ),
}


@register.simple_tag(name="icon")
def icon(name, css="", title=""):
    """Render a named inline SVG icon.

    ``{% icon "lock" %}`` → a 1em, currentColor lock glyph. ``css`` adds
    classes (e.g. sizing/colour); ``title`` adds an accessible tooltip and
    drops aria-hidden so screen readers announce it.
    """
    path = _ICON_PATHS.get(name)
    if path is None:
        return ""
    if title:
        aria = format_html(' role="img" aria-label="{}"', title)
    else:
        aria = mark_safe(' aria-hidden="true"')
    title_el = format_html("<title>{}</title>", title) if title else ""
    return format_html(
        '<svg class="parletre-icon {}" viewBox="0 0 24 24" width="1em" height="1em" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"{}>{}{}</svg>',
        css,
        aria,
        title_el,
        mark_safe(path),
    )
