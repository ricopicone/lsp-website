"""Seed wording for the Applications Coordinator's messages.

``{placeholder}`` tokens are substituted at send time (see
``services.render_template``); unknown tokens are left intact so a hand-edited
template can never crash a send.

Tokens:
- acknowledgment / decision_*: ``{name}``, ``{track}``, ``{formation}``, ``{status_url}``,
  ``{guidelines_url}``, ``{availability_url}`` (pre-sorted to advisors),
  ``{documents_url}``, ``{profile_url}``, ``{mylsp_url}``, ``{note}`` (decisions),
  ``{applications_coordinator}``
- invitation: ``{interviewer}``, ``{applicant}``, ``{formation}``, ``{agree_url}``,
  ``{applications_coordinator}``
- introduction: ``{applicant}``, ``{interviewer}``, ``{applicant_email}``,
  ``{interviewer_email}``, ``{applications_coordinator}``
- interview_reminder: ``{interviewer}``, ``{applicant}``, ``{url}``,
  ``{applications_coordinator}``
"""

from __future__ import annotations

# ruff: noqa: E501 — the message paragraphs read as written; don't rewrap.

SEED_TEMPLATES: dict[str, tuple[str, str]] = {
    "acknowledgment": (
        "We received your LSP application",
        """Dear {name},

Thank you for applying to the {track} at the Lacanian School of Psychoanalysis. We've received your letter of intent and CV.

Next, you'll be put in contact with two Analysts of the School to schedule two interviews. Your application is then reviewed at the monthly Meeting of the Analysts, after which we'll be in touch about the decision.

You can check the status of your application any time here:

{status_url}

Feel free to contact me should you have any questions.

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
    "invitation": (
        "Can you interview an LSP applicant?",
        """Dear {interviewer},

A new applicant to the Lacanian School of Psychoanalysis, {formation}, needs two Analysts of the School to interview them. Our records show you may be available for application interviews.

If you are willing to conduct one of the interviews, please let us know here:

{agree_url}

That page will confirm whether an interviewer is still needed and tell you a little more. The first two analysts to agree are connected with the applicant to arrange a time — so there's no obligation if the slots are already filled.

With thanks,

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
    "introduction": (
        "LSP interview — {applicant} and {interviewer}",
        """Dear {applicant} and {interviewer},

Thank you both. {interviewer} has kindly agreed to conduct one of {applicant}'s admission interviews for the Lacanian School of Psychoanalysis.

Please reply to this email to arrange a time to meet. Your contact addresses:

- Applicant: {applicant} <{applicant_email}>
- Interviewer: {interviewer} <{interviewer_email}>

After the interview, the interviewer submits a short report from their Analyst page; once both interviews are reported, the Meeting of the Analysts decides.

Warm regards,

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
    "interview_reminder": (
        "Reminder: your LSP interview with {applicant}",
        """Dear {interviewer},

This is a friendly reminder about the admission interview you agreed to conduct for {applicant}. If you haven't yet, please arrange a time to meet — and once you've had the interview, record your report here:

{url}

The Meeting of the Analysts can't decide until both interview reports are in. Thank you for your help.

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
    "decision_accept": (
        "Welcome to LSP — your application has been accepted",
        """Dear {name},

It is my great pleasure to inform you that your application to the Lacanian School of Psychoanalysis, {formation}, has been accepted. You are now a Precandidate at LSP: Congratulations!

The first thing for you to do now is to choose an advisor among the Analysts of the School. The Formation Guidelines explain the responsibilities of advisor and advisee:

{guidelines_url}

You can see which analysts are currently available to advise here:

{availability_url}

Note that it is up to you to contact the analyst you have selected and ask them if they can be your advisor.

In the members-only documents area you will also find a checklist of what is needed before you present your Passage, and the two founding texts of the school used in the creation of one's Palimpsest:

{documents_url}

Please also take a few minutes to build your LSP member profile — add your bio, photo, and contact details — and explore your member home, My LSP:

{profile_url}

{mylsp_url}

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

{note}With my best wishes,

{applications_coordinator}
LSP Applications Coordinator
applications@lacanschool.org""",
    ),
}
