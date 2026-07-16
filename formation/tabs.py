"""The My LSP hub's tab list — the single source of truth shared by the hub
view (``formation.views.formation``) and the avatar-menu context processor, so
the menu and the in-page tab bar agree on which tabs a member has.

Kept deliberately cheap: it runs on every page via the context processor, so it
uses role/standing *properties* (no per-page queries) except the rare
``is_lsp_member`` membership fallback. Tuition/Account key on the obligation
properties here; the hub view passes ``tuition``/``account`` overrides so it can
*also* surface them when there's payment history (``show_money_tab``).
"""

from __future__ import annotations

from django.conf import settings

#: Tabs every authenticated member always has, in display order.
_HEAD = [
    ("formation", "Formation"),
    ("groups", "Groups"),
    ("events", "Events"),
    ("works", "Works"),
]


def available_tabs(user, *, tuition=None, account=None):
    """Ordered ``(key, label)`` tabs available to ``user`` for the My LSP hub.

    ``tuition`` / ``account`` default to the member's obligation properties;
    pass a bool to override (the hub view forces them on when payment history
    exists). ``account`` is the unified "My account" tab (task #439) — one
    running balance across dues, tuition, and registration charges; it
    replaces the old standalone "Dues" tab.
    """
    if not getattr(user, "is_authenticated", False):
        return []

    from accounts.permissions import is_lsp_member
    from payments.dues import is_dues_obligated

    profile = getattr(user, "profile", None)
    member = is_lsp_member(user)

    show_tuition = (profile is not None and profile.owes_tuition) if tuition is None else tuition
    show_account = is_dues_obligated(user) if account is None else account

    tabs = list(_HEAD)
    if show_tuition:
        tabs.append(("tuition", "Tuition"))
    if show_account:
        tabs.append(("account", "My account"))
    if member:
        tabs.append(("proposals", "Proposals"))
    if member and getattr(settings, "SUGGESTIONS_ENABLED", False):
        tabs.append(("suggestions", "Suggestions"))
    tabs.append(("profile", "Profile"))
    return tabs
