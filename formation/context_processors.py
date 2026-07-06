"""Expose the My LSP hub's available tabs to every page, so the avatar menu can
render "My LSP" with the member's tabs indented beneath it."""

from __future__ import annotations

from .tabs import available_tabs


def my_lsp_tabs(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"my_lsp_tabs": []}
    return {"my_lsp_tabs": available_tabs(user)}
