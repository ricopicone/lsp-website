# A PC-created program event is born unregisterable

**Task:** #532 (triage of John's email).
**Date:** 2026-08-09

## The report

John, the Program Committee Chair, direct-created a late-addition seminar for
Marcelo Estrada and wrote:

> I followed those steps to add Marcelo's seminar but it seems to be stuck as a
> draft. When I first filled out the "add event" page I set the seminar to a
> draft so I could review the event page before publishing. I then went back in
> and changed it to "open to registration"; however, when I go to the seminar
> listings it still says it is a draft. Is that a bug or am I missing a step in
> the process?

It is a bug, and the field he changed is not the one the badge reads.

## What was actually wrong

Prod state for `psychoanalytic-training-2026-27` at the time of triage:

```
status=open  published=False  is_public_now=True  badge='Draft'
price_tiers=0  sessions=0  registrations=0
```

Three symptoms, one cause.

### The two switches

`Event.status` (Draft / Open for registration / Closed) is the field on the
add-event form. John set it to Open and it stuck. Visibility is a **separate**
field, and for an annual-program type (seminar, reading group, cartel) it is
supposed to cascade from the owning `Program` rather than from the event's own
`published` flag — `Program.is_public_now` is documented as the lever, and
`program_admin_special_event_publish` refuses to toggle a program event for
exactly that reason:

> Filtered to special events so a program event, whose visibility cascades from
> its Program, can't be toggled here.

The cascade is implemented in `Event.is_public_now` and honoured by the detail
view. **It is honoured nowhere else.** `Program.public_program_year_q()` — the
Q-expression helper written for Event-side querysets — is defined at
`events/models.py:136` and never called from anywhere in the codebase.

So the badge John was looking at (`Event.registration_badge`), the Register CTA,
the draft banner, the register view's gate, the landing list, and the calendar
feed all read the raw `Event.published` boolean, which for his seminar was
`False` — while the event was simultaneously public per `is_public_now`.

### Why it never surfaced before

All fifteen other 2026-27 events were script-imported with `--publish`, so
`published=True` masked the split entirely. Marcelo's is the first program event
ever created through the PC form, and that form does not expose `published` at
all. Combined with the special-event publish view's deliberate refusal, **there
was no button anywhere John could have pressed.** He did not miss a step.

### The deeper divergence

There are two ways a program event comes into being:

1. **Member proposes → PC approves.** `EventProposal.approve()` mints a
   *complete* event — price tier (`_build_price_tier`), meeting series,
   speakers, workgroup provenance.
2. **PC direct-creates** via `program_admin_event_new` → `ProgramEventForm` → a
   *bare* `Event`: no price tier, no sessions, `published=False`.

The PC's *special-event* direct-create already resolved this by routing through
the proposal pipeline, and says so:

> Reuses the member proposal form + `EventProposal.approve()` pipeline so the
> minting (price tier, first session, speakers, workgroup provenance) is never
> duplicated.

The program-event path is the one that never got that treatment. All three of
John's symptoms — Draft badge, no price tier, no sessions — are that single
divergence. Without a price tier the registration form cannot be completed even
once published, so the event was unregisterable by two independent mechanisms.

## Immediate remediation (done 2026-08-09, before this design)

Marcelo's seminar was unblocked on prod directly, since fall registration is
open and a deploy cycle is not free:

- `published=True`.
- One `PriceTier(audience=ALL, base_amount=500, sliding_scale=False,
  minimum_amount=0, covered_by_tuition=True)` — matching his `fee_note`
  ("$500 or School Tuition") and the shape `mint_program_tiers` uses for the
  other $500 seminars.

Verified anonymously: `/program/?year=2026-2027` badges it "Registration open",
and its workspace page serves a Register CTA with no draft banner, byte-for-byte
the same treatment as a known-good sibling (`das-unbehagen-2026-27`).

Sessions were left alone. `schedule_note` carries the pattern in prose ("last
two Thursdays each month"), and inventing occurrences is Marcelo's call.

## Design

One idea carries all three parts: a **price spec** — the five values that
already describe a price on the proposal form, lifted into something the PC
form, the faculty form, and the review loop can all share.

### `events/price_spec.py` (new)

A small value object plus functions, holding the vocabulary the app *already*
uses. `EventProposalForm.fee_type` is **Free / Fixed amount / Sliding scale**
(`events/forms.py:307`) with `fee_amount`, `fee_sliding_min`, `fee_sliding_max`,
`tuition_covers`, and a `clean()` that nulls the inputs which do not match the
chosen type and validates min ≤ max.

- `PriceSpec` — `fee_type`, `amount`, `sliding_min`, `sliding_max`,
  `tuition_covers`.
- `from_event(event)` — read the event's current price back into a spec.
- `apply_to_event(event, spec)` — reconcile the event's tier rows to the spec.
- `label(spec)` — a short human string ("$500, covered by tuition"; "Sliding
  $0–$100"), used by the review diff.
- `clean_spec(data)` — the validation rules, moved out of `EventProposalForm`.

`EventProposal._build_price_tier` is refactored onto `apply_to_event`, so
there is exactly one definition of what a price is and the two creation paths
cannot drift again.

**Deliberately not adopting `mint_program_tiers`' vocabulary.** That script
names its shapes fixed / donation / per-session, but those are a one-off
migration's categories, not the app's: "donation" is just sliding-from-$0 with a
suggested ceiling, and per-session is not representable in the model at all —
the script pre-multiplied rate × session count into a fixed base. Introducing
them would give the school two pricing vocabularies for one model.

### Part 1 — the cascade fix

Adopt the cascade at every site still reading the raw flag.

Sites that already hold an `Event` instance move to `Event.is_public_now`:

| Site | What it currently breaks |
|---|---|
| `events/models.py:577` `registration_badge` | The "Draft" John saw |
| `registrations/views.py:151` register gate | Registration 404s |
| `_event_summary.html:228` | No Register button |
| `_location.html:60` | Join/location block withheld |
| `event_detail.html:53` | "Draft preview (staff only)" banner |

Queryset sites move to `Program.public_program_year_q()`, finally using it:

| Site | What it currently breaks |
|---|---|
| `events/upcoming.py:40` | Absent from the landing list |
| `core/views.py:162` | Absent from the calendar feed |
| `events/views.py:137` | Absent from the events list |

`is_public_now` already falls back to `self.published` when an annual-program
event has no `Program`, and non-program types read `published` unchanged, so
every non-program event keeps its exact current behaviour.

After this, a PC-created program event is live the moment its program is —
which is what the architecture always said. `published=False` on such an event
becomes inert rather than fatal.

### Part 2 — the fee block on `ProgramEventForm`

Lift the proposal form's fee inputs into a shared mixin driven by the price
spec, and mount it on `ProgramEventForm` for both create and edit. The PC gets
the same three-way choice faculty already get when proposing.

Rejected: routing PC direct-create through `EventProposalForm` +
`approve()` as the special-event path does. It is the architecturally cleaner
answer and would supply sessions too, but `ProgramEventForm` carries fields the
proposal form has no notion of (`slug`, `status`, `access_info`,
`requires_faculty_approval`, `continues_seminar`) and is *also* the edit form
for existing events, where a proposal cannot apply. Sharing the spec gets the
anti-drift benefit without rebuilding the PC's create workflow.

### Part 3 — price as a reviewable field

`REVIEWABLE_FIELDS` gains `"price"` and `FIELD_LABELS["price"] = "Price"`, so a
faculty price change on an approved event routes through the existing
certify-or-submit dialog and the PC queue.

`EventChangeRequest` is field-parallel — `changed_fields` holds names,
`proposed_<f>`/`original_<f>` hold values, `apply()` does `setattr`. Price fits
that shape with two JSON columns, `proposed_price` and `original_price`, each
holding a spec dict. `getattr(self, f"proposed_{f}")` keeps working unchanged;
only two methods branch:

- `apply()` — for `price`, call `price_spec.apply_to_event()` instead of
  `setattr` + `save(update_fields=...)`.
- `field_changes()` — render both sides through `label()` rather than as raw
  values.

This binds only events minted from an approved proposal, since that is what
`requires_change_review()` scopes to. Marcelo's event, being PC-created, has no
originating proposal, so faculty edits to it apply immediately — unchanged
behaviour, and correct: nothing was reviewed, so there is nothing to diverge
from.

## Two safety properties

These are the places this could quietly destroy data or money, so they are
requirements, not notes.

**1. The spec addresses only the event-level `audience=ALL` tier.** Two 2026-27
seminars carry a second `audience=student` tier, and per-session tiers key off a
`Session` FK. An event whose tiers the spec cannot faithfully represent — more
than one event-level tier, or any session-scoped tier — renders its price
**read-only**, with a pointer to Django admin, rather than offering an edit that
would silently drop the other row. `apply_to_event` must refuse such an event
rather than reconcile it.

**2. A price change never re-prices an existing registration.**
`Registration.quoted_amount` is fixed when the member registers, and the ledger
reads charges and payments rather than the tier. Changing `base_amount` affects
only future registrations. This is correct and deliberate; it should not later
be "fixed" into a retroactive re-quote.

## Testing

- Cascade: a program event with `published=False` under a published program is
  badged "Registration open", serves a Register CTA, accepts registration, and
  appears in the landing list, calendar feed, and events list. The same event
  under an *unpublished* program does none of those.
- Non-program events (special event, Day of Assembly) keep reading `published`.
- An annual-program event with `program=None` still falls back to `published`.
- `price_spec` round-trips: after `apply_to_event(e, spec)`, `from_event(e)`
  equals `spec` — for each of free / fixed / sliding, with `tuition_covers`
  both ways.
- `EventProposal.approve()` still mints the same tier it did before the
  refactor (existing tests in `events/test_event_proposal.py` must stay green
  untouched).
- `apply_to_event` refuses a multi-tier event; the form renders read-only for
  one.
- A faculty price edit on an approved event creates a PENDING
  `EventChangeRequest`, leaves the live tier untouched, and applies the new
  price on PC approval.
- An existing registration's `quoted_amount` is unchanged by a price edit.

## Not in scope

- Sessions / meeting series on the PC direct-create path. The same divergence
  produces them, but the schedule UI is its own design and `schedule_note`
  carries the pattern in prose meanwhile.
- Per-session and student-rate pricing in the spec. Django admin keeps those,
  and the read-only guard makes the limit visible rather than dangerous.
- Any retroactive re-pricing of existing registrations.
