"""Seed wording for the Applications Coordinator's messages.

``{placeholder}`` tokens are substituted at send time (see
``services.render_template``); unknown tokens are left intact so a hand-edited
template can never crash a send.

Tokens:
- acknowledgment / decision_*: ``{name}``, ``{track}``, ``{note}`` (decisions only)
- interviewer_nudge: ``{interviewer}``, ``{applicant}``, ``{url}``
"""

from __future__ import annotations

# ruff: noqa: E501 — the message paragraphs read as written; don't rewrap.

SEED_TEMPLATES: dict[str, tuple[str, str]] = {
    "acknowledgment": (
        "We received your LSP application",
        """Dear {name},

Thank you for applying to the {track} at the Lacanian School of Psychoanalysis. We've received your letter of intent and CV.

Next, you'll be put in contact with two Analysts of the School to schedule two interviews. Your application is then reviewed at the monthly Meeting of the Analysts, after which we'll be in touch about the decision.

You can check your application status any time from your account.

— The Lacanian School of Psychoanalysis""",
    ),
    "interviewer_nudge": (
        "LSP: your interview report for {applicant} is awaited",
        """Dear {interviewer},

Thank you for agreeing to interview {applicant} for admission to the Lacanian School of Psychoanalysis. The Meeting of the Analysts is waiting on your interview report before it can decide.

When you've had the interview, please record your report here:

{url}

With thanks,

The LSP Applications Coordinator""",
    ),
    "decision_accept": (
        "Welcome to LSP — your application has been accepted",
        """Dear {name},

It is my great pleasure to inform you that your application to the Lacanian School of Psychoanalysis, {formation}, has been accepted. You are now a Precandidate at LSP: Congratulations!

The first thing for you to do now is to choose an advisor among the Analysts of the School. The members-only documents area has a document explaining the responsibilities of advisor and advisee, and you can see each analyst's current availability — including who is available to advise — here:

{availability_url}

Note that it is up to you to contact the analyst you have selected and ask them if they can be your advisor.

In the members-only documents area you will also find the latest Guidelines for the formation of analysts, a checklist of what is needed before you present your Passage, and the two founding texts of the school used in the creation of one's Palimpsest:

{documents_url}

Please also take a few minutes to build your LSP member profile — add your bio, photo, and contact details:

{profile_url}

Any questions about your formation should be directed to your advisor; feel free to contact me with anything else.

{note}Welcome to LSP!

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
    "decision_reject": (
        "Your LSP application",
        """Dear {name},

Thank you for your interest in the Lacanian School of Psychoanalysis and for the time you gave to the application process. After review at the Meeting of the Analysts, we are not able to offer you admission at this time.

{note}— The Lacanian School of Psychoanalysis""",
    ),
}
