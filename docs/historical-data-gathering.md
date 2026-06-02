# Gathering historical member data

## Why this exists

We can capture the **current** state of dues and tuition, but we can't
reconstruct **history**. The treasurer ledgers we imported only go back to AY
2024–25, and the data model stores each member's *current* role with **no
timeline** — so for any past year we cannot answer, from data alone:

- Was this person in the school that year, and in which role?
- Did they owe tuition that year (were they in-training)?
- Did they pay tuition / dues that year, or skip?
- How many of the required **four tuition years** have they completed?

Today we *guess* (e.g. we assumed the AY 2025–26 in-training roster was also
in-training in 2024–25). This document lists **exactly the data we need to
gather** to replace those guesses with facts, plus how to collect it (a
launch-time survey) and how to verify it against payment records later.

The receiving fields already exist on `accounts.Profile`
(`year_joined`, `role`, directory fields) and `payments`
(`TuitionPeriod` / `TuitionEnrollment` / `Payment` / `DuesPeriod`); the
**membership timeline** and a **provenance flag** are the two genuinely new
pieces (see *Data-model implications* at the end).

---

## The data we need — per member

### A. Identity & matching keys
*Purpose: link a survey response to the right `User`, and to payment records
that use inconsistent names/emails (the ledgers had `Garet`/`Garret`,
`Wu Bing`/`Winnie Wu`, etc.).*

1. Full name (as it should appear) + **any alternate spellings / names used on payments**.
2. Login email (have) + **any other email addresses** used for Stripe, PayPal, or to send checks.
3. Preferred display name / pronouns *(have fields; confirm)*.

### B. Membership timeline — the critical gap
*Purpose: determine, for every past year, whether the member owed tuition and/or
dues. This is the single most important block.*

4. **Year they joined the school** (`Profile.year_joined` — have the field, often empty).
5. **Role history with start years** — the AY they entered each role along the track:
   `student → pre-candidate → candidate → analyst` (and the scholar track:
   `pre-candidate scholar → candidate scholar → scholar`).
6. **Year they finished / transitioned out of in-training** (completed the four tuition years), if applicable.
7. **Leave / hiatus years** — any years they were inactive, on hiatus, or had left
   (the dues crossref sheet noted "Hiatus", "left the school", "N/A").
8. Current role *(have; confirm — drives present-day obligations)*.

### C. Tuition history
*Purpose: reconstruct per-year tuition status and the four-year completion count.*

9. **Per academic year they were a student**: tuition paid in full / paid in
   installments / **skipped** / comped / waived.
10. **Which of the four required tuition years they've completed**, and in which years.
11. Amount paid per year if known (rates changed over time — e.g. $2,000 then $2,500).
12. How each tuition payment was made (school Stripe / PayPal / check / cash) — for verification.

### D. Dues history
*Purpose: reconstruct per-year dues participation.*

13. **Per year of membership**: dues paid? (yes / no / hiatus-exempt).
14. Amount paid per year if known (tiered $50 / $100 / $150 by role).
15. Payment method per year, if known — for verification.

### E. Payment-verification handles
*Purpose: reconcile self-reported answers against authoritative records when we
get them — names and emails on the ledgers rarely match the directory.*

16. Name exactly as it appears on their **card / PayPal / checks**.
17. Email/account used for **each** platform (Stripe receipt email, PayPal email).
18. Anything that pins a payment: approximate dates, amounts, or "I always paid by check".

### F. Profile / directory enrichment
*Not needed for reconstruction, but the survey is the natural moment to fill
these. All are existing `Profile` fields, frequently empty.*

19. Bio, headshot, credentials, languages spoken, location, phone, public-listing email.
20. Website, specialties / focus, consultation modalities, timezone.
21. Faculty flag (`is_faculty`) — needed so seminar instructors can edit events / mint codes.

---

## Collection plan — launch / account-setup survey

- **Trigger:** first login after launch (account setup), then available from the
  profile area. A short reminder banner until completed.
- **Pre-fill everything we already have** (name, email, current role, `year_joined`,
  imported bio/credentials) so members *confirm or correct* rather than re-type.
- **Two parts**, so the easy part isn't blocked by the hard part:
  - *Part 1 — Profile* (quick): confirm identity + directory fields (block F).
  - *Part 2 — History* (best-effort): the timeline grid (block B) and a
    **year-by-year checklist** for tuition and dues (blocks C/D). Present as a
    grid of academic years with "paid / installments / skipped / not in school"
    options — far easier to recall than free text.
- **Framing:** "to the best of your memory"; allow "don't remember". Partial is fine.
- **Provenance:** every value the survey produces is stored as **self-reported**,
  distinct from values **verified** against records (see below).

## Verification & fallback

Survey answers are provisional. When authoritative records arrive, reconcile:

- **Match** → promote the record from *self-reported* to *verified*.
- **Conflict** (survey says paid, record says not, or different amount) → flag
  for the treasurer to resolve; don't silently overwrite.
- **No record but survey says paid** → keep the survey value as the **fallback**
  (this is the explicit "fall back to survey responses" path).

This requires distinguishing self-reported vs verified data (provenance flag,
below) so a later record import doesn't clobber a confirmed value and we can
report "X% of history is verified vs self-reported".

## Authoritative records to chase (non-survey)

These let us *verify* and reduce reliance on memory:

- **Full Stripe transaction/payout export, all years** — names, receipt emails, amounts, dates.
- **PayPal transaction history** (the ledgers show some PayPal dues).
- **Bank statements / check images** for offline (check/cash) payments.
- **Older treasurer spreadsheets** (pre AY 2024–25) — dues, tuition, and seminars.
- **Wix / Google Group membership history** — useful for join dates and role timing.

## Data-model implications (future build — not yet built)

The blocks above mostly land in existing fields, **except**:

- **Membership / role timeline.** `Profile` has a single current `role` and a
  single `year_joined` — no per-year role history. Needed to compute "owed
  tuition that year" and the four-year completion count historically. Likely a
  new `RoleHistory` / `MembershipPeriod` model (role + start AY [+ end AY]), or
  a per-year enrollment-style record. Until it exists, per-year obligation is
  derived by proxy/assumption.
- **Provenance flag.** A `source` (`self_reported` | `verified`) on
  `TuitionEnrollment` and `Payment` (today we only have free-text `notes`, e.g.
  the `[assume-skip …]` / `[tz-import …]` tags). Lets verification promote
  values and lets the treasurer dashboard show how much history is confirmed.
- **Tuition-years-completed** could then be a derived count over verified +
  self-reported enrollments, surfaced per student.
