# Referral response: one checkbox, no "unavailable"

**Task:** #531 (triage of Diana's email requests), first request.
**Date:** 2026-08-08

## The request

Diana, the Referral Coordinator, asked that the option to say "unavailable" be
removed from clinicians. Not from one response — from the form itself, for
everyone. A clinician who cannot take a referral should be free to let the
request pass without filing anything.

## Today

`referrals.forms.RespondForm` renders `available` as a required
`TypedChoiceField` over a `RadioSelect`: **I'm available** / **Not available**.
`ReferralResponse.available` is a plain `BooleanField(default=True)` with no
third state, so the data model already has only two facts to tell: a row exists
and says available, or it does not exist. `available=False` is a stored
non-answer.

Nothing downstream consumes it. `ReferralRequest.interested_responses()` filters
`available=True`, and every consumer — `services.build_followup`'s
none/one/many variant split, the detail page's "N clinicians available so far",
the dashboard's Available column — reads through that helper. An unavailable
response is already invisible to the requester. It surfaces in exactly two
places: a grey "not available" badge on Diana's request detail page, and the
`available` column/filter in Django admin.

So this is a form-and-copy change, not a data-model change.

## Design

### The clinician's respond page

`RespondForm.available` becomes `forms.BooleanField(required=False)` rendered as
a single checkbox, labelled **I'm available to work with this person**, above
the existing optional note to the coordinator. Below it, one line of copy:

> If you're not available, you can simply ignore this request. No response is
> needed.

That is a message, not a control. There is nothing to click that means "no".

Because the checkbox is the state rather than a declaration, submitting it
unchecked is not saying "unavailable" — it is having no response on file. The
`respond` view branches on `cleaned_data["available"]`:

- **checked** — save as today (`recorded_by=None`, `available=True`), success
  message unchanged.
- **unchecked, a row exists** — delete the row; "Your response was withdrawn —
  you are no longer listed as available for referral {reference}."
- **unchecked, no row** — no-op, same withdrawn message.

This gives a clinician who said yes in week one and filled up in week two a way
to take it back, without the word "unavailable" appearing anywhere. The
self-service path never writes `available=False` again.

The page's intro copy ("if you respond as available, the Referral Coordinator
sends them your practice details") and the "You responded … (available / not
available)" line get matching edits, since a stored response can now only mean
available.

### Diana's side

`RecordResponseForm` — the escape hatch for responses that arrive by email or in
conversation — loses its **Available / Not available** select the same way. It
records a clinician plus an optional note; `record_response` writes
`available=True` unconditionally. The corresponding label in `detail.html` goes
with it.

To keep the manual override complete (REG-14, "space for the singular"), each
response row on the request detail page gains a small **Remove** action — a
coordinator-only POST to a new `referrals:remove_response` route — so a response
Diana recorded, or one a clinician wants pulled, can be taken off the request.
Removal is confirmed through the repo's `<dialog>` pattern rather than firing on
a single click.

### What deliberately does not change

- **The `available` field stays on `ReferralResponse`.** Historical
  `available=False` rows keep their meaning and keep rendering their existing
  grey badge; nothing is rewritten or migrated. `interested_responses()` keeps
  filtering on it, so `build_followup`, the counts, and the dashboard column are
  untouched.
- **The seeded `MessageTemplate` copy stays verbatim.** The `distribution`
  template already says "If you are available to work with this person, please
  respond on the site" — it invites an available answer and never offers a
  negative one. Diana's wording is not paraphrased (see
  `referrals/seed_templates.py`).
- **`followup_none`'s "there were no responses to your request"** stays as it
  is. It was already reached by counting only available responders.

### Documentation

`core/docs/referrals-guide.md` (the Help tab) describes the response step and
the manual-record escape hatch. Two short edits: note that clinicians who are
not available simply do not respond, and that recording manually no longer asks
for availability.

## Testing

Rewrite `test_clinician_can_respond_and_update`, which currently posts
`available: "False"` and asserts the row flips. New and revised cases in
`referrals/tests.py`:

- checking the box creates one `available=True` row with `recorded_by=None`
- posting unchecked with a prior response deletes it (zero rows) and reports it
  as withdrawn
- posting unchecked with no prior response is a clean no-op, not an error
- the respond page renders no "Not available" text and no radio input
- `record_response` writes `available=True` when the form carries no
  availability field
- `remove_response` deletes a response for the coordinator and is forbidden to a
  non-coordinator
- the existing follow-up variant tests keep passing unchanged, which is the
  proof that dropping the negative answer did not disturb the none/one/many
  split.
