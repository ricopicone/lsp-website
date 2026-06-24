"""Seed wording for the Applications Coordinator's messages.

``{placeholder}`` tokens are substituted at send time (see
``services.render_template``); unknown tokens are left intact so a hand-edited
template can never crash a send. Tokens for the interviewer nudge:
``{interviewer}`` (the analyst's name), ``{applicant}`` (the applicant's name),
and ``{url}`` (the review page).
"""

from __future__ import annotations

# ruff: noqa: E501 — the message paragraphs read as written; don't rewrap.

SEED_TEMPLATES: dict[str, tuple[str, str]] = {
    "interviewer_nudge": (
        "LSP: your interview report for {applicant} is awaited",
        """Dear {interviewer},

Thank you for agreeing to interview {applicant} for admission to the Lacanian School of Psychoanalysis. The Meeting of the Analysts is waiting on your interview report before it can decide.

When you've had the interview, please record your report here:

{url}

With thanks,

The LSP Applications Coordinator""",
    ),
}
