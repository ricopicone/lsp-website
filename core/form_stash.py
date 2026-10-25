"""Carry a refused form across the redirect back to the page it came from.

Several forms post from a panel on a larger page and redirect back, so a
refused submission used to lose what was typed and report its error in a
message at the top of the page, far from the form (task #820, the #817
lesson). The POST rides the session for exactly one render; the page rebinds
its form to it, so the errors sit under their fields with the values intact.
"""

from __future__ import annotations

from django.utils.datastructures import MultiValueDict

_PREFIX = "form_stash:"


def stash(request, key: str) -> None:
    """Keep ``request.POST`` (less the CSRF token) for the next render."""
    request.session[_PREFIX + key] = {
        name: values for name, values in request.POST.lists()
        if name != "csrfmiddlewaretoken"
    }


def take(request, key: str) -> MultiValueDict | None:
    """The stashed POST for ``key``, removed as it is read, or None."""
    data = request.session.pop(_PREFIX + key, None)
    return None if data is None else MultiValueDict(data)
