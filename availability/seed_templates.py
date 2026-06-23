"""Seed wording for the analyst-availability reminder.

``{placeholder}`` tokens are substituted at send time (see
``services.render_template``); unknown tokens are left intact so a hand-edited
template can never crash a send. Available tokens: ``{name}`` (the analyst's
name), ``{update_url}`` (their sign-in link to the availability section of the
profile editor), and ``{applications_coordinator}`` (the appointed
coordinator's name).
"""

from __future__ import annotations

# ruff: noqa: E501 — the reminder paragraphs read as written; don't rewrap.

SEED_TEMPLATES: dict[str, tuple[str, str]] = {
    "review_request": (
        "Please review your availability — Lacanian School of Psychoanalysis",
        """Dear {name},

We keep a list of which Analysts of the School are available for Application Interviews, to serve as an Advisor, for Control analysis, and for Personal analysis. It helps us route requests to the right colleagues.

Please take a moment to review and update your availability:

{update_url}

The link signs you in and takes you straight to the Availability section of your profile. Thank you for keeping it current.

Sincerely,

{applications_coordinator}""",
    ),
}
