# Member intake survey + history models

Companion to [historical-data-gathering.md](historical-data-gathering.md). That
doc lists *what* we need; this one drafts the **survey** members fill out at
launch and specs the **data models** that store and reconcile it.

Design rule for the survey: **friendly and short.** Most fields are pre-filled
confirmations; the only real "work" is one year-grid. Everything is best-effort
("your best guess is fine") and skippable. Target: ~3 minutes.

---

## Part 1 — The survey

Shown once at first login after launch (and re-openable from the profile menu
until completed). A small dismissible banner nudges incomplete members.

### Screen 1 — Welcome

> ### Welcome to the new LSP site 👋
> We're moving our records over and want yours to be right. This takes about
> **three minutes**, and you can answer from memory — **best guesses are
> totally fine**, we'll double-check against our records where we can.
>
> [ Get started ]   ·   _You can finish this later from your profile._

### Screen 2 — You  (pre-filled; confirm or fix)

Only four fields, all pre-filled from what we already have:

- **Your name** — `[ María Líza Ahearne ]`  _(edit if it's wrong)_
- **Current role at LSP** — `[ Candidate Analyst ▾ ]`  _"Not right? Pick the correct one."_
- **Pronouns** _(optional)_ — `[            ]`
- **Roughly what year did you join LSP?** — `[ 2019 ]`  _"A year is all we need — a guess is fine."_

> Tiny footnote: _"Your role and join year help us figure out which years you
> owed tuition or dues — that's all we use them for."_

### Screen 3 — Your years at LSP  (the one real question)

The high-value block. A compact grid — check the years you **paid tuition**
and/or **paid dues**. Pre-checked from any records we already have (so members
correct rather than recall), and rows below their join year are dimmed.

```
  Your years at LSP
  Check the years you paid. Leave blank for years you skipped or weren't enrolled.
  Don't sweat exactness — we verify against records where we can.

                              Paid          Paid
                              tuition       dues
   ┌────────────────────────┬────────────┬────────────┐
   │ AY 2025–26  (current)  │    ☐       │    ☑       │
   │ AY 2024–25             │    ☑       │    ☑       │
   │ AY 2023–24             │    ☑       │    ☐       │
   │ AY 2022–23             │    ☐       │    ☑       │
   │ AY 2021–22             │    ☐       │    ☑       │
   │ AY 2020–21  ·············· before you joined, dimmed ··········· │
   └────────────────────────┴────────────┴────────────┘
   ☐  I paid for some years before this list — roughly: [ 2017 ]–[ 2019 ]

   Tuition note: students owe four years total; you've marked 2 so far.  ← live count
```

- Rows: current AY back to a few years before the earliest record we have
  (cap ~8 visible; the "before this list" escape hatch covers older years
  without a long scroll).
- The live "you've marked N of 4" tuition counter gives gentle feedback and
  doubles as a sanity check.
- "Dues" column hidden for roles that don't owe dues; "tuition" column hidden
  for non-student roles — so faculty/analysts see a one-column or no grid.

### Screen 4 — Paying under a different name?  (optional, skippable)

Only because the ledgers are full of name/email mismatches:

> Did you ever pay by a **name or email different from your account**? If so,
> tell us so we can find those payments. _(Skip if not.)_
>
> - Other name on your payments: `[                 ]`
> - Other email (Stripe / PayPal): `[                 ]`
>
> [ Skip ]   [ Finish ]

### Screen 5 — Done

> ### Thanks — you're all set ✅
> We'll match this against our records and reach out only if something doesn't
> line up. Want to polish your public profile while you're here?
> [ Edit my profile ]   [ Go to the site ]

**That's the whole survey:** confirm 4 fields, one grid, one optional line.
Nothing else is asked — bios, photos, specialties, etc. live in the existing
profile editor and are offered as an *optional* follow-up, never required here.

---

## Part 2 — The models

Three additions. None replace `Profile.role` (it stays the live cache that
drives present-day access/pricing); they add **history** and **provenance**.

### 2a. `MembershipTenure` — the role timeline

The missing piece: which role a member held in which years, so we can compute
per-year obligations instead of proxying.

```python
class MembershipTenure(models.Model):
    """One stint in one role. A member's tenures, ordered by start_ay,
    reconstruct their role at any past academic year."""
    user     = FK(User, related_name="tenures")
    role     = CharField(choices=Profile.Role.choices)
    start_ay = PositiveSmallIntegerField()          # AY start year, e.g. 2019
    end_ay   = PositiveSmallIntegerField(null=True) # null = ongoing
    source   = CharField(choices=Source.choices)    # see 2c
    notes    = TextField(blank=True)

    # helpers
    @classmethod
    def role_at(cls, user, ay) -> str | None: ...
    @classmethod
    def was_in_training(cls, user, ay) -> bool: ...   # role_at ∈ IN_TRAINING_ROLES
```

- **Derives** the things we can't answer today: was this member in-training in
  AY 2022–23? (→ did they owe tuition?), what was their tier for dues that year?
- **Stays consistent with `Profile.role`:** the open tenure (`end_ay is None`)
  mirrors `Profile.role`; a save signal (or a thin `set_role(role, ay)` helper)
  closes the previous tenure and opens a new one when role changes. Profile.role
  remains the fast path everything else already reads.
- From the survey we seed **approximate** tenures (current role back to
  `year_joined`); precise transition years get filled as records/old
  spreadsheets arrive, upgrading `source` to `verified`.

### 2b. Capturing dues/tuition from the survey

- **Tuition:** a checked "paid tuition" year → `TuitionEnrollment(user, period,
  status=PAID_IN_FULL, source=SELF_REPORTED)`. An in-training year left unchecked
  → `SKIPPING` (same policy as the backfill, but now self-reported by the member
  rather than assumed). "Four years owed" becomes a real derived count:
  `TuitionEnrollment.objects.filter(user, status__paid).count()`.
- **Dues:** a checked "paid dues" year → `Payment(type=DUES, dues_period=period,
  status=SUCCEEDED, method=OFFLINE, source=SELF_REPORTED, amount=<tier for their
  role that year>)`. Amount is the best estimate from `MembershipTenure.role_at`
  × the period's tier; flagged self-reported so a real record can correct it.
  *(Requires `Payment.amount` to stay required — we estimate rather than null it.)*

### 2c. Provenance — `Source`

A shared flag so a later authoritative import **promotes** values instead of
clobbering them, and the treasurer can see how much history is confirmed.

```python
class Source(models.TextChoices):
    VERIFIED      = "verified",      "Verified against records"
    IMPORTED      = "imported",      "Imported from treasurer ledger"
    SELF_REPORTED = "self_reported", "Member-reported (survey)"
    ASSUMED       = "assumed",       "Assumed (e.g. unpaid → skipping)"
    STAFF         = "staff",         "Entered/edited by staff"
```

Add `source = CharField(choices=Source.choices, db_index=True)` to
**`TuitionEnrollment`** and **`Payment`**. Data migration backfills existing
rows from their `notes` tags: `[tz-import …]` → `IMPORTED`,
`[assume-skip …]` → `ASSUMED`, everything else → `STAFF`/`VERIFIED` as
appropriate. (Stripe-completed live payments → `VERIFIED`.)

### 2d. `MemberIntakeSurvey` — the raw submission

Keep the raw answers so we can re-derive if our logic changes and keep an audit
trail separate from the structured records it generates.

```python
class MemberIntakeSurvey(models.Model):
    user         = OneToOneField(User)
    submitted_at = DateTimeField(null=True)
    year_joined  = PositiveSmallIntegerField(null=True)
    payment_names  = CharField(blank=True)   # alternate names on payments
    payment_emails = CharField(blank=True)
    grid         = JSONField(default=dict)    # {"2024": {"tuition": true, "dues": true}, ...}
    applied_at   = DateTimeField(null=True)   # when reconciled into the structured models
```

On submit: store `grid` verbatim, update `Profile.year_joined`, then generate
the `MembershipTenure` / `TuitionEnrollment` / `Payment` rows above
(`source=SELF_REPORTED`). Re-applying is idempotent (keyed on user+period).

---

## Part 3 — Reconciliation (when real records arrive)

For each authoritative record (Stripe/PayPal export, old spreadsheet) matched to
a `(user, period, type)`:

| Situation | Action |
|---|---|
| Record agrees with a self-reported row | set `source = VERIFIED` (+ real amount/date) |
| Record exists, member didn't report it | create `VERIFIED` row |
| Member reported it, no record found | **keep** the `SELF_REPORTED` row (the fallback) |
| Record conflicts with member's claim | flag for the treasurer — don't auto-overwrite |

The treasurer Tuition/Dues tabs gain a small **source badge** per row and a
"**% verified vs self-reported**" line, so it's obvious how trustworthy each
year's picture is.

---

## Part 4 — Suggested build order

1. **Models + provenance** (2a–2d) and the backfill migration tagging existing
   rows. Low-risk, unblocks everything; ship behind no UI.
2. **Survey** (Part 1) wired into post-launch first-login, writing to
   `MemberIntakeSurvey` and generating self-reported rows. Pre-fill from
   existing data.
3. **Treasurer source badges + verified %** (cheap, high trust value).
4. **Reconciliation tooling** (Part 3) — run as records come in; can start as a
   management command mirroring `import_treasurer_payments`.

Phase 1 is independent of launch; phase 2 should land with the launch survey.
