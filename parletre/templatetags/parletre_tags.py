"""Template helpers for Parlêtre (nav gating + inline SVG icons)."""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from parletre.permissions import can_enter_parletre

register = template.Library()


@register.filter(name="is_parletre_member")
def is_parletre_member(user) -> bool:
    """True if ``user`` may enter Parlêtre (drives the nav link) — members plus
    auditors, who are then confined to their seminar channel."""
    return can_enter_parletre(user)


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
    # --- treasurer admin actions (task #439) ---
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "trash": (
        '<path d="M3 6h18"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    ),
    "undo": (
        '<path d="M9 14 4 9l5-5"/>'
        '<path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5H11"/>'
    ),
    "tag": (
        '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 '
        '2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a'
        '2.426 2.426 0 0 0 0-3.42z"/>'
        '<circle cx="7.5" cy="7.5" r=".5"/>'
    ),
    "user-plus": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<line x1="19" x2="19" y1="8" y2="14"/>'
        '<line x1="22" x2="16" y1="11" y2="11"/>'
    ),
    # remove a person from a roster
    "user-minus": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<line x1="22" x2="16" y1="11" y2="11"/>'
    ),
    "eraser": (
        '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 '
        '5.6c1 1 1 2.5 0 3.4L13 21"/>'
        '<path d="M22 21H7"/><path d="m5 11 9 9"/>'
    ),
    "pencil": (
        '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>'
        '<path d="m15 5 4 4"/>'
    ),
    "rotate-ccw": (
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>'
    ),
    "sticky-note": (
        '<path d="M16 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11l5-5V5a2 2 0 0 '
        '0-2-2Z"/><path d="M15 21v-4a2 2 0 0 1 2-2h4"/>'
    ),
    # a comped admission (registrar console)
    "ticket": (
        '<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 '
        '2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/>'
        '<path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/>'
    ),
    "split": (
        '<path d="M16 3h5v5"/><path d="M8 3H3v5"/>'
        '<path d="M12 22v-8.3a4 4 0 0 0-1.172-2.872L3 3"/>'
        '<path d="m15 9 6-6"/>'
    ),
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
    # video meeting room
    "video": (
        '<path d="m23 7-7 5 7 5V7z"/>'
        '<rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>'
    ),
    # forum (threaded) — overlapping square bubbles
    "forum": (
        '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/>'
        '<path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/>'
    ),
    # chat (live) — single round speech bubble
    "chat": (
        '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 '
        '8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 '
        '4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'
    ),
    # add-a-reaction smiley
    "smile": (
        '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/>'
        '<line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>'
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
