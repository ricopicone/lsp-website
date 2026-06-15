"""Template context for the suggestion widget.

Surfaces a single boolean, ``show_suggestion_widget``, that gates the floating
"Suggest a change" button, the avatar-menu "My Suggestions" link, and the footer
link — true only when the feature is enabled and the viewer may submit a
suggestion (Board members + superusers). Mirrors
``core.context_processors.survey_nudge``.
"""

from __future__ import annotations

from django.conf import settings


def widget(request):
    user = getattr(request, "user", None)
    if not (
        getattr(settings, "SUGGESTIONS_ENABLED", False)
        and user is not None
        and user.is_authenticated
    ):
        return {"show_suggestion_widget": False}

    from .permissions import can_submit_suggestion

    return {"show_suggestion_widget": can_submit_suggestion(user)}
