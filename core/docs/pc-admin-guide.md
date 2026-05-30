# Program Committee Admin Guide

*A walk-through of the Program Committee admin: planning, editing, and
publishing the LSP annual program (seminars, reading groups, cartels).*

---

## What this admin is for

The Program Committee owns the LSP **annual program** — the set of
seminars, reading groups, and cartels offered each academic year.
This admin lets you:

- See every program (across academic years) at a glance.
- Edit a program's events directly (title, faculty, dates, description,
  etc.).
- Control when each program becomes publicly visible (publish toggle
  + scheduled publish date).
- Create new events attached to a program.

What this admin doesn't do (yet): solicit and review event proposals
from faculty. That workflow is designed but deferred. For now, the PC
writes the program directly using this admin.

---

## How to get there

1. Log in at <https://app.lacanschool.org/> with your LSP account.
2. Click your photo / initials in the top-right.
3. Pick **Program Committee admin**.

You'll see the dropdown link if you're a current member of the
**Programming Committee** on the committees list (or if you're LSP
staff with full admin access).

---

## Programs tab (the index)

Lists every program. Each row shows:

- **Academic year** (the program's label, e.g. "Program 2026-2027")
- **Status** — **Public** (visible on `/program/`) or **Draft** (hidden
  from anyone outside the PC + staff)
- **Events** — count of seminars + reading groups + cartels in the
  program
- **Publish date** — if scheduled, the date it will flip to Public
  automatically

An upcoming academic year is set up automatically about a year ahead,
so you should always see at least the current year and the next year
here. The next year starts as **Draft** so you can plan ahead without
exposing anything publicly.

Click **Open** on any row to drill in.

---

## Program detail page

Two sections:

### Publication

- **Published now** checkbox — flip this to make the program (and all
  its events) immediately visible on `/program/?year=…`.
- **Schedule a publish date / time** — pick a future date/time when
  the program should automatically become public. Useful for
  announcing the new year on a specific date.

Either being set is enough — once `publish_date` is in the past, the
program is treated as Public.

> **Effect of publishing:** when the program is Public, all of its
> events become visible on `/program/?year=…` and accessible via their
> individual URLs. While Draft, only the PC + staff can preview the
> program at that URL.

### Events

Below the publication section, the program's events are grouped:

- **Seminars** (event_type = seminar)
- **Reading groups + cartels** (event_type = reading_group or cartel)

Each row links to its edit page. Click **+ New event** at the top to
add a new one attached to this program.

> Special events, Days of Assembly, Working Days, and Scholarly
> Seminars are **not** part of the annual program. They live on
> `/events/` and are managed separately.

---

## Event edit / create form

- **Title** + **Slug** — the slug is the URL fragment
  (`/events/<slug>/`). Keep it short and lowercase-hyphenated.
- **Event type** — limited to the annual-program types: seminar,
  reading group, cartel.
- **Start / end date** — the academic-year range the event spans (used
  by the program page and by the unified calendar).
- **Format** — online / in person / hybrid.
- **Status** — draft / open for registration / closed. This is
  registration-status (whether people can sign up), separate from the
  program's public-visibility status.
- **Description** — Markdown-friendly long-form text shown on the
  event page.
- **Access info** — Zoom link, meeting code, address, etc. Hidden from
  the public; released to registrants only after they've paid.
- **Faculty** — the LSP-affiliated instructors. Only users with
  `is_faculty=True` show up in this picker.

> The event is auto-attached to the program you're editing in — you
> don't have to set the program field.

After saving, a "View event page" link takes you to the public-facing
URL (which only the PC + staff can see while the program is Draft).

---

## Common workflows

### "We're ready to announce the 2027-28 program."

1. Edit each event in the program detail page until they're correct.
2. On the program detail page, check **Published now**.
3. Done. The program is now public at `/program/?year=2027-2028`.

### "We want to release the 2027-28 program on August 15 at noon."

1. Same as above, but instead of checking **Published now**, set
   **Schedule a publish date / time** to `2027-08-15 12:00`.
2. The program stays Draft until that moment, then auto-publishes.

### "I need to add a new seminar to the current year."

1. Open the program for the current year.
2. Click **+ New event**.
3. Fill in the form and save.
4. The event is attached to the program and visible (if the program is
   already Public).

### "I need to change a seminar's description."

1. Open the program containing the seminar.
2. Click **Edit** next to the seminar.
3. Update the description and save.

### "I need to take a seminar down from the public site."

The program's publish state is the main lever — when the program is
public, all its events are visible; when it's draft, none are. Hiding
a single event without un-publishing the whole program isn't a
routine workflow. If this comes up often, ask the Web Coordinator to
add a per-event hide control.

### "Someone proposed an event I want to add — how does that work today?"

Today: a faculty member sends you the details by email or in
conversation, and you create the event in the program admin. A formal
proposal workflow (faculty submits a form → PC reviews + votes →
approve mints an Event) is in the roadmap below.

---

## What's coming (roadmap)

- **Proposal workflow**: faculty submits a structured event proposal
  via a form; PC reviews + comments; approve mints an Event. Replaces
  the current ad-hoc proposal-by-email-then-PC-types-it-in flow.
  Designed; build deferred until after this year's manual cycle.
- **Batch clone** for setting up next year from last year's structure
  ("two-week ordeal" → half-day).

> Faculty can already edit descriptions on events they teach today —
> they don't need to wait for the proposal workflow to land for that.

---

## When to ask the Web Coordinator for help

- Adding a new PC member to the committee list (so they can access this
  admin).
- Anything that looks wrong or broken.
- Anything you'd like to do that this admin doesn't yet handle.
