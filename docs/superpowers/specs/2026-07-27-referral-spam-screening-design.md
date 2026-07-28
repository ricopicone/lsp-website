# Referral spam screening — design (task #479)

**Status:** approved, ready for an implementation plan
**Date:** 2026-07-27

## The incident

Referral request `26-0727` was a bot. What it submitted, verbatim from prod:

```
name     = 'LEIAZKMKtfUBswyJuaS'
pronouns = 'IzNydkEnQFrKxxKl'        (picked "Other", typed into pronouns_other)
location = 'lfNxcMPRAZNciaxtfNPOMQK'
language = 'iIcIlrhZIIwEImoxJld'
email    = 'lauren_michele2005@hotmail.com'
modality = all three boxes checked
info     = 'GtDlqAgHoujeYbXggDwPs'   (21 characters)
```

A commodity form-spam bot: every visible text input filled with a random
mixed-case token, every checkbox checked, a radio picked. The email is the one
field that is not random — almost certainly harvested from someone real.

**Why the existing honeypot missed it.** `ReferralRequestForm.website` is a
`forms.HiddenInput` — `type="hidden"`. This bot skipped it, which is what
commodity bots do, because a hidden input is the textbook honeypot. It
demonstrably fills every *visible* text input it finds. The signup form's
honeypot (`accounts/antibot.py`, task #471) is a visible-in-DOM text input
hidden by CSS — the variant this bot would have walked into. The better tool
was already written; the form that got hit was using the weaker one.
`antibot.py`'s docstring names this form as the intended next adopter.

**Blast radius.** Prod runs `ack=auto dist=auto`:

- The auto-acknowledgment mailed `lauren_michele2005@hotmail.com`, a third
  party who never contacted the school. This is the task #471 reputation risk
  realized: unsolicited mail from the SES identity that also carries dues,
  receipts, and referrals.
- Auto-distribution pushed it to the whole active referral list, and one
  clinician responded to gibberish.
- Follow-up is `review`, so it stopped before replying to the "requester".

Two facts that shape the design. `26-0727-2` (three and a half hours later) is
a **genuine** request, so nothing about that day can be distrusted wholesale.
And the contrast is stark: real requests run 600–900 characters of coherent
prose; the junk was one 21-character token with no spaces.

## Decisions

1. **Quarantine only the suspicious.** Clean submissions flow exactly as they
   do today — auto-ack, auto-distribute, no added delay. Only a submission that
   trips a heuristic is held. Auto mode was chosen deliberately; this preserves
   it for the requests that deserve it.
2. **Near-certain bots are dropped but counted.** No record, no email, ordinary
   success page. A counter gives the hit rate without a junk pile, and without
   a bot's text ever landing in front of a human.
3. **Held requests alert by bell only**, not email. The one exception is the
   escalation in §8, which emails a request left unreviewed for days — the
   default stays quiet, but a false positive cannot rot.
4. **No IP or user-agent is stored** on `ReferralRequest`.

## 1. Where the checks live

Two kinds of check, split because they have different inputs and different
failure modes.

**Transport checks** — honeypot, fill timing, per-IP cap. These need the HTTP
request. `accounts/antibot.py` already implements all three; the
Find-an-Analyst form adopts them as-is. Verdict: **silent drop**.

**Content checks** — a new `referrals/screening.py`: a pure function of the
submitted dict returning `(suspicious, reason)`. No request, no I/O, trivially
testable. Verdict: **HELD**.

The content screen belongs to `referrals`, not `accounts`, because "is this a
real referral request" is referral-domain knowledge, while `antibot` stays a
generic primitive any public form can adopt. It is called from
`services.intake()` rather than the view, so every caller is covered.

## 2. Form fix (`accounts/forms.py`)

Replace the `HiddenInput` honeypot and `clean_website` with the task #471
pattern:

- `antibot.HONEYPOT_FIELD` as a CSS-hidden **text** input (`class="hp-field"`,
  `tabindex="-1"`, `autocomplete="off"`). The field name stays `website`.
- `antibot.TIMESTAMP_FIELD`, the signed render stamp.
- A `honeypot_tripped` property the view inspects.

The `ValidationError("Bot detected.")` is removed — it tells the bot exactly
which field burned it. A caught bot gets the ordinary success page and learns
nothing.

Minimum fill time becomes a per-form parameter on `antibot.looks_too_fast`.
Signup keeps 2 seconds; this form gets **10**, because it is a multi-step
wizard with seven fields and no human clears it faster. Only *too fast* is
caught — a slow requester with the page open for an hour is unaffected.

`.hp-field` is already plain CSS in `assets/css/input.css` from #471, which
matters here: the class is set in Python, so Tailwind would drop it if it
existed only in Python (see the `tailwind-classes-set-in-python` gotcha).

## 3. New states on `ReferralRequest`

Two additions to `Status`:

- **`HELD`** — screened as suspicious. Not acknowledged, not distributed,
  waiting on the coordinator.
- **`JUNK`** — terminal. Never set by the automatic path (which only ever
  holds); set by the coordinator.

New fields:

- `held_reason` (text) — what tripped, so the coordinator can judge at a glance.
- `held_at` (datetime, null) — drives escalation.
- `held_escalated_at` (datetime, null) — so escalation fires once.

`OPEN_STATUSES` stays `(NEW, ACKNOWLEDGED, DISTRIBUTED)`. `HELD` gets its own
dashboard filter and count so it never silently enters the normal workflow;
`JUNK` is excluded everywhere.

## 4. Intake flow

`services.intake()` gains one branch, after the existing duplicate guard:

- **Suspicious** → create with `status=HELD`, record `held_reason` and
  `held_at`, send **no** acknowledgment, run **no** distribution, and fire a
  bell to the referral-coordinator role holders. No coordinator inquiry email.
- **Clean** → exactly today's behavior.

`distribute()` and `send_acknowledgment()` each grow a guard refusing HELD and
JUNK, so no future caller — cron, view, or admin — can leak a held request to
the referral list. The branch is the fix; the guards are what keep it fixed.

The bell reuses the existing `Category.REFERRAL_REQUEST` rather than minting a
new category, which would add a preference row for every member to no benefit.

## 5. Coordinator actions (request detail page)

- **Release** (HELD → NEW) — resumes the normal chain: acknowledges if auto,
  distributes if auto. A false positive costs the requester the review delay
  and nothing else.
- **Mark as junk** (any status → JUNK) — the escape hatch for the
  coherent-but-fake request no heuristic will ever catch. Stamps who and when
  into `coordinator_notes`, matching the `staff_notes` audit convention.
- **Not junk** (JUNK → NEW) — reversible, same audit note.

This is the do-not-over-automate requirement: the automatic path can only ever
*hold*, and a human makes every terminal call.

## 6. The heuristics (`referrals/screening.py`)

Each check yields a reason string; any hit holds. Thresholds are module-level
constants documented with the real payloads that motivated them.

- **Gibberish token** in `name`, `location`, `language`, `pronouns` (the last
  already resolved through `pronouns_display()` at intake). A field is a
  *candidate* only if it is at least 8 characters and `isalpha()` — letters
  only, so anything with a space, digit, slash, comma, or hyphen is never
  screened. A candidate is gibberish on one signal: **at least 4 case
  transitions** (adjacent letters changing upper↔lower).

  **Vowel ratio was evaluated and rejected.** It looks reasonable and is a
  liability. At the obvious threshold of 0.25 it flags `Pittsburgh` (0.20 — an
  actually-submitted location), `Frankfurt` (0.22), `Bydgoszcz` (0.11), and
  `they/them` (0.22). Lowering the threshold to clear those drops it below the
  junk tokens it was meant to catch. There is no setting that separates the two
  populations, so the signal is not used.

  Case transitions separate them cleanly. All five junk tokens score well over
  the threshold — `lfNxcMPRAZNciaxtfNPOMQK` 5, `LEIAZKMKtfUBswyJuaS` 6,
  `IzNydkEnQFrKxxKl` 11, `iIcIlrhZIIwEImoxJld` 12, `GtDlqAgHoujeYbXggDwPs` 15 —
  while every real value we hold scores 1: `Pittsburgh`, `Edmonton`, `English`,
  `Frankfurt`, `Bydgoszcz`. The nearest real-world miss is `MacDonald` at 3,
  under the threshold; `McCann` scores 3 but is below the 8-character floor
  anyway. The `isalpha()` gate is what keeps `they/them` and `she/her` out.

  **Known limit:** an all-lowercase gibberish bot (`qwrtplkjhg`) scores 0
  transitions and is not caught here. That is accepted rather than patched with
  a consonant-run heuristic — the transport checks in §2 are the first line, and
  this bot's narrative would still trip the length rule below. Revisit only if
  a lowercase variant actually appears.
- **Narrative too short**: `additional_information` under 40 characters.
  `26-0727` was 21; Tina's was ~900 and Maloney's ~700.
- **URLs or markup** in any field — `http`, `www.`, `[url=`, `<a `. Near-zero
  false positives on real requests, and the standard SEO-spam vector.

These hold rather than reject precisely because they are fallible. Non-English
names and place names are what a gibberish heuristic gets wrong, and it will
happen eventually.

**Privacy.** No IP or user-agent is stored on `ReferralRequest`. These rows
carry sensitive clinical disclosures and are redacted on retention; adding an
identifier creates new privacy surface for little gain. The per-IP cap uses the
cache, exactly as signup does.

## 7. Blocked counter

A minimal `BlockedSubmission` model — `created_at` and `reason`, **no content,
no address**. It cannot leak, and it makes "blocked 14 automated submissions
this month" a real number on the referrals dashboard. Without it, a filter that
silently broke and started eating real requests would look identical to a
filter that is working. `process_referrals` prunes rows over 12 months old.

## 8. Escalation

`process_referrals` runs daily already. Any HELD request older than
`ReferralSettings.held_escalation_days` (new field, default 3) sends the
coordinator one email and stamps `held_escalated_at` so it never repeats. This
keeps the bell-only default while bounding what a false positive costs a real
person who may be in distress.

## 9. Tests

The regression bar is the real data:

- The actual `26-0727` payload screens as **held**, and each of its five junk
  tokens is asserted individually — a whole-payload test would pass even if
  four of the five signals silently broke.
- The actual Tina and Maloney payloads screen **clean**. This is the test that
  matters most — over-blocking a genuine request is worse than the incident.
- `MacDonald`, `Edmonton`, `English`, `Pittsburgh`, `Frankfurt`, `Bydgoszcz`,
  `they/them`, and `San Antonio Texas` screen clean, so the false-positive
  margin is pinned rather than assumed. `Pittsburgh` and `they/them` are there
  specifically because the rejected vowel-ratio rule flagged both.

Beyond that:

- Honeypot filled → success page, no `ReferralRequest`, counter incremented.
- Too-fast submission → same.
- Per-IP cap.
- A held request sends neither acknowledgment nor distribution, but does bell.
- Release resumes the chain (acks and distributes under auto settings).
- `distribute()` and `send_acknowledgment()` refuse HELD and JUNK.
- Mark-as-junk and not-junk write the audit note.

## 10. Ops

One migration: the two status choices, `held_reason` / `held_at` /
`held_escalated_at`, the `ReferralSettings` field, and `BlockedSubmission`.

One-off on prod after deploy: set `26-0727` to `JUNK` with a coordinator note.

No new environment variable, no feature flag.

## Out of scope

- Notifying the clinicians who received `26-0727` that it was junk, or anything
  toward the third party who was auto-acknowledged. Both are the coordinator's
  and Web Coordinator's calls, not code.
- CAPTCHA of any kind. The evidence says a correctly built honeypot stops this
  class of bot, and a CAPTCHA taxes every genuine requester — people reaching
  out about caregiving, eating disorders, and abuse — to stop something three
  invisible checks already stop.
