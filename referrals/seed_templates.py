"""Seed wording for the referral message templates.

The acknowledgment, the three follow-up variants, and the New Member
Instructions are the Referral Coordinator's own wording, verbatim (Diana
Cuello, 2026-06-11) — do not paraphrase or restyle. The only edits are the
ones the in-site process genuinely requires: ``{placeholder}`` tokens where
her drafts had "XYZ" or a blank, and the New Member Instructions' steps 1
and 3 now point at the self-service profile editor instead of emailing her
the information. The distribution template (step 3) had no prior wording —
she sent the requests by hand — so that one is ours, as is the addendum
(task #531), and like all of these both are editable on the Templates page.

Used by the seed data migration and by ``MessageTemplate.get`` to restore a
deleted row.
"""
# ruff: noqa: E501 — the verbatim paragraphs must not be rewrapped.

SEED_TEMPLATES: dict[str, tuple[str, str]] = {
    "acknowledgment": (
        "Lacanian School of Psychoanalysis - Received your request for referral",
        """Dear {name},

Thank you very much for contacting the Lacanian School of Psychoanalysis. Your request has been received and is being processed. It will take about 2 weeks for me to send you the names of clinicians available to work with you.

Sincerely,

Diana C. Cuello, PhD

Referral Coordinator

On behalf of LSP""",
    ),
    "addendum": (
        "LSP referral request {reference} - additional information",
        """Dear colleague,

There is additional information about referral {reference}:

{addendum}

If you are available to work with this person, please respond on the site by {due_date}:

{respond_url}

If you have already responded and this changes your answer, you can update it on the same page.

Sincerely,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP""",
    ),
    "distribution": (
        "LSP referral request {reference}",
        """Dear colleague,

A new request for referral has come in through the LSP website. The requester's name and email are withheld; everything else they shared is below.

Referral {reference}
Pronouns: {pronouns}
Location: {location}
Preferred language: {language}
Preferred modalities: {modalities}

{details}

If you are available to work with this person, please respond on the site by {due_date}:

{respond_url}

Responding there connects your response to the number of the referral, and your practice information (as set in your profile) will be sent to the requester.

Sincerely,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP""",
    ),
    "followup_many": (
        "Lacanian School of Psychoanalysis - Response to your request for referral",
        """Greetings:

Please find below the names of clinicians affiliated with LSP available to work with you. Since your request has remained confidential to all of them, it is now up to you to contact those clinicians.

Wishing you the best on your analytical journey.

Sincerely,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP

{clinicians}""",
    ),
    "followup_one": (
        "Lacanian School of Psychoanalysis - Response to your request for referral",
        """Greetings:

Please find below the name of the clinician affiliated with LSP available to work with you. Since your request has remained confidential, it is now up to you to contact the clinician.

Wishing you the best on your analytical journey.

Sincerely,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP

{clinicians}""",
    ),
    "followup_none": (
        "Lacanian School of Psychoanalysis - Response to your request for referral",
        """Greetings:

I regret to inform you that there were no responses to your request for an analyst. I suspect the reason is that in-person membership in {location} is limited. If you would like to resubmit your request expanding to virtual practices, please let me know. If you have any other questions please don't hesitate to reach out.

Wishing you the best on your analytical journey.

Sincerely,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP""",
    ),
    "onboarding": (
        "New Member Instructions",
        """Dear {name},

Here's some information to orient you to the referral process in preparation for the first time you respond to a request.

1- Could you please set your information in your profile on the LSP website ({profile_url}):

Name

Title

e-mail

Phone #

You are welcome to include more or less information. Some members only share name and phone number, or just name and email- Others include additional info such as a website or psych today profile. This is the information your potential analysand will receive from me.

2- I will add your information to my list of clinicians. You can respond to request emails (please respond through the link in the email, as it will connect your response to the number of the referral) and I will send out your information.

3- If your information changes, please update it in your profile. I will assume no changes and rely on your profile unless you update it.

Warmly,

Dr. Diana C. Cuello

Referral Coordinator

On behalf of LSP""",
    ),
}
