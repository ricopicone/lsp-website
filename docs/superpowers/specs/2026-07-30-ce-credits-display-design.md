# Continuing-education credits and accreditor logos on events

Task #486. 2026-07-30.

## The problem

Some LSP events are approved by outside bodies for continuing-education (CE)
credits, and those bodies require the event page to display their logo and, in
most cases, a fixed block of approval language. Nothing on the site can do this
today.

`SeminarProposal.offers_ce` exists — a checkbox reading "Offer APA CE credits
(you apply to GPPA separately)" — but it dies at approval. `approve()` never
copies it, `Event` has no CE field of any kind, and no template renders it. The
only trace of CE on the live site is a sentence a human typed into one seminar's
description during the 2025-26 program import:

> Note: CE credits are available for this seminar (2 per meeting).

The school does not want to curate a collection of accreditor images. Whatever
we build has to let faculty supply the logo themselves.

## Shape of the solution

CE is recorded **on the Event**, by whoever can already edit that event, on the
event edit form. The accreditor logos live in a **shared library that grows by
use**: faculty tick the bodies that approved their event, and add one inline
when theirs is not listed yet. Nobody curates it; it accretes.

## Decisions

### The logo library is shared, not per-event

A per-event upload would mean the APA logo is uploaded once per faculty member
per year, with a different crop each time and no way to fix them all when APA
revises its mark. A `CEOrganization` row is created the first time someone needs
it and reused by everyone after, and the body's mandated approval language,
which is a property of the organization rather than of any one event, has an
obvious home.

Rejected: a per-event override upload on top of the library. It buys a case
that does not appear to exist (one accreditor with two logos) at the cost of a
branch on every render.

### CE lives on the event edit form, not the Workspace Settings tab

The Settings tab belongs to a `Workgroup`. Seminars and reading groups have
their own; special events, Days of Assembly, Working Days, and the Scholarly
Seminar Series share the Programming Committee's, so a CE section there would be
the *committee's*, not the event's — and a visiting speaker's special event is
among the likeliest things to carry CE credits.

The edit form already owns every publicly displayed event field and is gated by
`can_edit_event` (event faculty, PC, LSP Staff, Django staff), which is exactly
the right set and is identical across event types. So the answer to "where do I
change what my event page says?" stays one place.

While we are here: the link to that page is labelled **"Edit description"** in
both `events/event_detail.html` and the Workspace masthead, which has been stale
since the form grew title, readings, schedule, contact, fee, and speaker
sections. It becomes **"Edit event"**, and `EventDescriptionForm` is renamed
`EventEditForm` (six references).

### CE changes apply immediately

The edit form routes changes to `REVIEWABLE_FIELDS` (title, description,
readings, fee note) through the certify-or-submit dialog for approved events.
The CE fields are **not** added to that set. An accreditation is a factual
record of a decision an outside body already made, not program content the
Programming Committee vetted, so it applies immediately like `schedule_note` and
`contact`.

### The credit count carries a basis

A year-long seminar quotes credits **per meeting** ("2 per meeting", as the
2025-26 import shows); a one-day special event quotes a **total** ("6 CE
credits"). One number cannot say both, and forcing a seminar to state a total
would make faculty quote a figure that depends on how many meetings actually
happen.

So: one decimal `ce_credits` plus a `ce_credits_basis` choice of *total* or *per
meeting*. Decimal, not integer, because 1.5 credits is a real award.

Rejected: a free-text credits string. It would render any future "which events
carry CE?" listing impossible and would invite a different phrasing from every
faculty member.

### Many organizations, one credit figure

Co-approving bodies compute contact hours from the same clock time and so
almost always land on the same number. A plain `ManyToMany` with the credit
figure on the `Event` covers co-approval, which is exactly the case that
produces more than one logo on a page. A through-model carrying per-organization
counts is deferred; the per-event note can carry an exception if one ever
appears.

### Two text slots, at two different levels

- `CEOrganization.statement` — the body's required approval language. Written
  once when the organization is first added, rendered under its logo on every
  event that claims it, and correctable in one place if the body revises its
  wording.
- `Event.ce_note` — the per-event exception: full attendance required for
  credit, certificates issued within two weeks, psychologists only.

Both optional. An organization with no mandated language on an event with
nothing special to say renders as a logo and a credit line.

### The proposal collects intent, not facts

At proposal time the accreditation has not happened — the propose page tells
faculty they apply to GPPA separately. So the proposal keeps its `offers_ce`
checkbox and gains an optional expected credit count (`ce_credits` +
`ce_credits_basis`, mirroring the Event so `approve()` is a straight copy). The
organizations and their logos are set on the event edit form once the approval
is actually in hand.

This keeps the library seeded only by people holding an approval, rather than by
a proposer guessing at which body will grant one.

## Data model

New `events.CEOrganization`:

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField(120)` | Unique case-insensitively, enforced by a `UniqueConstraint(Lower("name"))`; the form turns a collision into a readable error |
| `logo` | `ImageField` | Public bucket, `upload_to="ce-organizations/"` |
| `url` | `URLField(blank)` | Wraps the logo in a link to the accreditor |
| `statement` | `TextField(blank)` | The body's mandated approval language |
| `added_by` | `FK(User, SET_NULL, null)` | Provenance |
| `created_at` | `DateTimeField(auto_now_add)` | |

Ordered by `name`.

New fields on `Event`:

| Field | Type | Notes |
|---|---|---|
| `offers_ce` | `BooleanField(default=False)` | Master switch; drives the render |
| `ce_credits` | `DecimalField(5,2, null, blank)` | Blank = approved but count not set |
| `ce_credits_basis` | `CharField(choices)` | `total` / `per_meeting`, default `total` |
| `ce_note` | `TextField(blank)` | Per-event exception |
| `ce_organizations` | `M2M(CEOrganization, blank)` | `related_name="events"` |

New fields on `SeminarProposal`: `ce_credits`, `ce_credits_basis` (same types
and choices). `approve()` copies `offers_ce`, `ce_credits`, and
`ce_credits_basis` onto the minted `Event`.

One migration. No backfill: the 2025-26 seminar whose description mentions CE by
hand is left alone, since re-recording it structurally is a data decision for
the Programming Committee, not part of this change.

## Editing

`EventEditForm` (renamed from `EventDescriptionForm`) gains `offers_ce`,
`ce_credits`, `ce_credits_basis`, `ce_note`, and `ce_organizations` (rendered as
checkboxes, each with its logo). None are added to `REVIEWABLE_FIELDS`.

Unchecking `offers_ce` hides the section from the public page but **does not
clear the stored values**, so a faculty member who unchecks it while an
accreditation lapses does not lose their organization selection and note.

Adding an organization is a separate small form on the same page — name, logo,
URL, statement — posted to a new view gated by `can_edit_event` for the event it
was reached from. On success it creates the organization, **attaches it to that
event**, and redirects back: reaching "add an organization" from an event can
only mean this event is approved by it.

A name matching an existing organization case-insensitively is a form error
naming that entry and pointing the user at the checkbox, not a second row.

### Logo processing

New `events/ce_images.py`. Validates the uploaded format and size, downscales to
fit an 800x400 box **preserving aspect ratio and alpha**, re-encodes to WebP,
and raises on anything unreadable so the form can report it.

Deliberately not `accounts/images.py`: that pipeline force-crops to a centred
square, which is right for a headshot and would mangle a wordmark.

### Staff escape hatch

`CEOrganization` gets a Django admin registration so staff can replace a bad
logo, correct mandated wording, or delete a duplicate that slipped past the name
guard.

## Display

New partial `events/_ce_credits.html`, rendered from `events/_event_summary.html`
at the bottom of the About section. That partial is shared by the public event
page and the Workspace Overview tab, so both surfaces get it from one file.

It renders whenever `offers_ce` is on, **independently of whether a description
exists** — About is currently wrapped in `{% if event.description %}`, and a CE
event with no description written yet would otherwise silently drop the whole
block. With a description it sits inside About; without one it stands alone.

Layout, compact by intent:

- A small uppercase "Continuing education" label rather than an `h2` competing
  with the About heading.
- One credit line: "Approved for 2 CE credits per meeting", "Approved for 6 CE
  credits", or "CE credits available" when the count is not set.
- A wrapping row of logos at `max-h-12 max-w-36 object-contain`, each linked to
  its organization's URL when it has one, `alt="{name} logo"`.
- Any organization statements, then `ce_note`, at `text-xs`.

**Logo chips stay paper-white in both themes.** Accreditor logos are
near-universally dark-on-transparent and would disappear against `abyss`. This
follows the header-crest precedent rather than inventing a rule.

Copy on this block uses commas rather than em dashes, per the member-facing site
copy convention.

## Testing

- The CE block renders on the public event page and the Workspace Overview tab;
  it is absent when `offers_ce` is off; it renders when the description is empty.
- Credit-line phrasing for each basis and for the no-count case.
- CE fields save immediately on an approved event without triggering the
  change-review dialog.
- Inline organization add: creates the row, attaches it to the originating
  event, and rejects a case-insensitively duplicate name with a pointer to the
  existing entry.
- Logo normalization: an oversized image is downscaled within the box, aspect
  ratio and alpha survive, an unreadable file is rejected.
- `approve()` carries all three CE fields from proposal to minted event.
- The three existing `Edit description` assertions in
  `events/test_faculty_views.py` are updated to the new label.

## Out of scope

- A CE marker on the program page or the events list. The task specifies the
  About section; listing surfaces can follow if asked.
- Per-organization credit counts (through-model).
- Certificates, attendance tracking, or anything that reports CE to a body.
- Re-recording the 2025-26 seminar's hand-typed CE sentence as structured data.
