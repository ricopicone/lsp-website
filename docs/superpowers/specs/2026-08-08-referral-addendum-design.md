# Referral addendum: telling the clinicians something changed

**Task:** #531 (triage of Diana's email requests), second request.
**Date:** 2026-08-08

## The request

> The most recent referral request (26-0804) is specifically looking for a
> sliding scale. Is there a way I can add an addendum to the distributed request
> through the site? I'm happy to simply send an amendment email, but figured I'd
> ask.

There is no such way today. Once `services.distribute` has gone out, the only
remaining outbound step is the step-5 follow-up, which goes to the *requester*.
Nothing in the app sends a second message to the clinicians.

## Naming

The app already uses "follow-up" for step 5 (`build_followup`,
`send_followup`, the `followup_none/one/many` templates, the Compose follow-up
button). This feature is called an **addendum** throughout — model, template
key, URL, and UI copy — so the two never blur together.

## Design

### The audience is now a recorded fact

`distribute()` mails `ReferralListMember.objects.filter(is_active=True)` and
keeps no record of who that was, so "the clinicians this request went to" cannot
be reconstructed afterward. Distribution starts logging it:
`ReferralRequest.distributed_to`, an M2M to `ReferralListMember`, populated on
send with `.add()` so repeated sends accumulate rather than replace.

An addendum sent to everyone also puts the request in front of a clinician who
was not on the list at distribution time, so addendum sends add to the same log.
The field therefore means *clinicians who have received this request*, which
stays true across any number of sends.

### Composing and sending

A new **Addendum** action on the coordinator's request detail page
(`/admin-tools/referrals/<reference>/addendum/`), available while the request is
DISTRIBUTED or REPLIED, refused on CLOSED, purged, and suppressed (HELD / JUNK)
requests through the existing `_refuse_if_suppressed` guard.

The compose form has three inputs:

1. **Addendum text** — what changed, in Diana's words. Required.
2. **Audience** — a two-way choice:
   - *Only the clinicians this request went to* — `distributed_to`, further
     filtered to `is_active=True` (someone since taken off the list is not
     mailed), shown with its count. The default when the log is non-empty.
   - *Everyone on the referral list* — every active member.
3. **Response deadline** — prefilled with the request's current
   `responses_due_at`, so leaving it alone changes nothing; moving it forward
   extends the window for a request whose terms just changed.

**The empty-log case.** Requests distributed before this ships have no recorded
recipients — including 26-0804, the one that prompted the feature. The narrower
option renders disabled and labelled "not recorded for this request", and the
audience defaults to everyone. Guessing a set and presenting the guess as the
recorded one would be worse than saying it plainly. In practice the two sets are
likely identical for 26-0804.

`services.send_addendum(req, text, audience, sent_by, responses_due_at=None)`
resolves the recipients, renders a new seeded `MessageTemplate` key `ADDENDUM`
with tokens `{reference}`, `{addendum}`, `{due_date}`, `{respond_url}`, mails
each clinician individually, adds them to `distributed_to`, writes the
`ReferralAddendum` row, and updates `responses_due_at` when it changed.

Like `distribution` and `acknowledgment` — and unlike the step-5 follow-up — the
template sends as seeded rather than through a per-send edit box. Diana rewrites
the wrapper wording on the Templates tab, where all her wording already lives.
Seed text is a plain skeleton, deliberately not an imitation of her voice.

### What it leaves behind

`ReferralAddendum`: `request` (FK, `related_name="addenda"`), `text`, `audience`,
`recipient_count`, `sent_at`, `sent_by` (FK to user, `SET_NULL`).

- **Diana's detail page** lists them as an audit trail, each reading like "Aug 8,
  2026, sent to 36 clinicians (everyone on the list)".
- **The clinician respond page** shows them under the request details, dated, so
  someone opening the link a week later sees the sliding-scale note without
  hunting through email. A clinician who already checked "available" can uncheck
  it in light of the addendum, which is the withdrawal path built in the first
  half of this task.

### Delivery

Recipients are reached individually through the notifications center on the
existing `REFERRAL_REQUEST` category, so the addendum inherits the bell, each
member's email preference, and the anonymity of the original distribution. It
needs its own wrapper — `notifications.referral_addendum()` — because
`referral_request()` hard-codes the title "Referral request {reference}" and the
body "A new anonymized referral request is open for responses", and passes
`dedupe=True`, which would swallow the second bell row. The addendum wrapper
titles the row "Referral request {reference}, addendum" and does not dedupe, so
two addenda ring twice.

### Privacy

Addendum text is requester detail. `services.purge_expired` redacts it with
everything else when the retention window closes, alongside `name`, `email`,
`pronouns`, `additional_information`, and `coordinator_notes`. Nothing about
this feature is exempt from the purge.

### Deliberately not built

- **No auto/review toggle in `ReferralSettings`.** Every other sending step has
  one because the site can decide to send on its own. An addendum is always
  hand-written, so there is nothing to automate and nothing to review.
- **No recipient log retrofitted onto past distributions.** See the empty-log
  case above.
- **No reopening a closed request.** If the referral is closed, the addendum
  action is not offered.

## Testing

In `referrals/tests.py`:

- `distribute()` records its recipients in `distributed_to`
- an addendum to the distributed audience reaches exactly those clinicians, and
  not a member added afterward
- an addendum to everyone reaches the newly added member too, and adds them to
  `distributed_to`
- a clinician taken off the list (`is_active=False`) is not mailed by either
  audience
- the addendum text and reference appear in the sent email body
- submitting a later deadline moves `responses_due_at`; leaving it alone does not
- the addendum shows on the respond page and on the coordinator detail page
- the action is refused on a CLOSED request and on a HELD one
  (`SuppressedStatusError`)
- a non-coordinator gets 403
- `purge_expired` redacts addendum text
