# Program Committee Admin Guide

*A walk-through of the Program Committee admin: planning the LSP annual
program (seminars, reading groups, cartels), reviewing member proposals,
and handling faculty edits to published events.*

---

## What this admin is for

The Program Committee owns the LSP **annual program**—the set of
seminars, reading groups, and cartels offered each academic year.
This admin gives you four tabs:

- **Programs**: see every program (across academic years), edit its
  events, and control when it becomes public (publish toggle and
  scheduled publish date).
- **Proposals**: review event proposals submitted by members; approve
  one to mint it into a program, or decline it with a note. This tab is
  also where you **create and manage special events** directly.
- **Changes**: review faculty edits to the content of already-approved
  events, and see the history of self-certified and administrative
  changes.
- **Help**: this guide.

The Treasurer admin handles dues and tuition separately; this admin is
only about the program.

---

## How to get there

1. Log in at <https://app.lacanschool.org/> with your LSP account.
2. Click your photo / initials in the top-right and pick **Admin Tools**.
3. On the Admin Tools page, choose **Program Committee Admin**.

You'll see the **Admin Tools** entry, and the Program Committee Admin
panel on it, if you're a current member of the **Program Committee**
on the committees list (or LSP staff with full admin access).

---

## Programs tab (the index)

Lists every academic year that has been set up. Each row shows:

- **Academic year**: the program's label, e.g. "Program 2026-2027".
- **Status**: **Public** (visible on `/program/`) or **Draft** (hidden
  from anyone outside the PC and staff).
- **Events**: count of seminars, reading groups, and cartels in the
  program.
- **Publish date**: if scheduled, the date it will flip to Public
  automatically.

An upcoming academic year is set up automatically about a year ahead,
so you should always see at least the current year and the next year
here. The next year starts as **Draft** so you can plan ahead without
exposing anything publicly.

Click **Open** on any row to drill in.

---

## Program detail page

Two sections:

### Publication

- **Published now** checkbox: flip this to make the program (and all
  its events) immediately visible on `/program/?year=…`.
- **Schedule a publish date / time**: pick a future date/time when
  the program should automatically become public. Useful for
  announcing the new year on a specific date.

Either being set is enough—once `publish_date` is in the past, the
program is treated as Public.

> **Effect of publishing:** when the program is Public, all of its
> events become visible on `/program/?year=…` and accessible via their
> individual URLs. While Draft, only the PC and staff can preview the
> program at that URL.

### Events

Below the publication section, the program's events are grouped:

- **Seminars** (event_type = seminar)
- **Reading groups + cartels** (event_type = reading_group or cartel)

Each row links to its edit page. Click **+ New event** at the top to
add a new one attached to this program.

> Special events, Days of Assembly, Working Days, and Scholarly
> Seminars are **not** part of the publishable annual program—they're
> standalone events on `/events/`, each with its own live/draft state.
> You still create and manage **special events** here in the PC admin,
> from the **Proposals** tab (see below); the other standalone types are
> set up in Django admin.

---

## Event edit / create form

- **Title** and **Slug**: the slug is the URL fragment
  (`/events/<slug>/`). Keep it short and lowercase-hyphenated.
- **Event type**: limited to the annual-program types—seminar,
  reading group, cartel.
- **Start / end date**: the academic-year range the event spans (used
  by the program page and by the unified calendar).
- **Format**: online, in person, or hybrid.
- **Status**: draft, open for registration, or closed. This is
  registration-status (whether people can sign up), separate from the
  program's public-visibility status.
- **Description**: Markdown-friendly long-form text shown on the
  event page.
- **Access info**: Zoom link, meeting code, address, etc. Hidden from
  the public; released to registrants only after they've paid.
- **Faculty**: the LSP-affiliated instructors. Only users with
  `is_faculty=True` show up in this picker. Faculty can edit the event
  and mint pricing codes.
- **Continue an existing seminar** (new seminars only): make this a new
  yearly term of an existing seminar so its workspace, channel, and past
  members carry over (they renew by registering for this term). Leave
  blank for a brand-new seminar.
- **Requires faculty approval**: if set, each registration must be
  approved by the event's faculty before it's confirmed. Default off.
- **Record video**: automatically record the event's online meeting.
  Off by default; recordings are stored privately and shown per their
  visibility setting.

> The event is auto-attached to the program you're editing in—you
> don't have to set the program field.

After saving, a "View event page" link takes you to the public-facing
URL (which only the PC and staff can see while the program is Draft).

---

## Proposals tab

Any LSP member can submit an event proposal (a seminar, reading group,
or special event) from their **My LSP → Proposals** area. Teaching a
seminar confers faculty standing, granted automatically on approval.

- **Pending**: proposals submitted for review. A proposal the member
  only *saved* (a work-in-progress draft) never reaches this queue—it
  shows up here once they submit it. Each card shows the proposer, type,
  proposed date/time (or "TBD"), conveners, description, speakers, fee,
  readings, and contact.
- **Approve & mint**: turns the proposal into a real Event. A seminar
  or reading group is minted into the *proposed* academic year's
  program (you still publish that program separately); a special event
  is minted and published once it has a date, otherwise held until you
  set one.
- **Decline**: sends it back with an optional reason. The proposer can
  revise and resubmit.
- **Decided**: a table of already-approved and declined proposals, with
  a link to the minted event.

### Creating a special event directly

You don't have to wait for a proposal. Click **+ New special event** at
the top of this tab to create one yourself. It opens the same event form
(pre-set to a special event), and when you save you choose:

- **Create & publish**: the event goes live on `/events/` immediately
  (unless its date is still TBD, in which case it's held as a draft).
- **Save as draft**: the event is created but hidden from the public
  until you publish it.

This is a shortcut for the PC only: it creates and approves the event in
one step (the admin is the authority). A special event a *member*
proposes still comes through the **Pending** queue for review.

### Managing special events

The **Special events** list at the bottom of this tab is the home for
every standalone special event. Each row shows a **Live** or **Draft**
badge and lets you **Edit** its content or **Publish / Unpublish** it —
so a draft can be taken live (or pulled back) whenever you're ready,
without touching Django admin.

---

## Changes tab

When faculty edit the *content* of an already-approved event (title,
description, readings, fee note), the change routes through a
certify-or-submit dialog rather than silently going live. This tab is
where those land:

- **Pending review**: substantial changes the faculty member asked the
  PC to approve. The live event is untouched while a change is pending.
  Each item shows a side-by-side **Current** vs **Proposed** diff per
  field, and an advisory note of roughly what percentage of the
  description changed. **Approve & apply** writes the change onto the
  event; **Decline** rejects it with an optional reason.
- **History**: minor changes the faculty self-certified and staff
  administrative changes are already live—they're listed here for the
  record, along with every decided item.

Non-content fields (schedule note, contact, record-video) always apply
immediately and don't appear here.

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

### "A member proposed an event—how do I add it?"

1. Go to the **Proposals** tab.
2. Read the proposal under **Pending**.
3. Click **Approve & mint** to turn it into an Event (a seminar or
   reading group lands in the proposed year's program; a special event
   is minted directly), or **Decline** with a note to send it back.
4. For a seminar or reading group, open the program and edit the minted
   event if anything needs polishing, then publish the program.

### "I want to put on a special event (a one-off talk, screening, etc.)."

1. Go to the **Proposals** tab and click **+ New special event**.
2. Fill in the form (title, date/time, description, fee, speakers…).
3. Click **Create & publish** to put it live now, or **Save as draft**
   to hold it until you're ready.
4. A draft appears in the **Special events** list; click **Publish**
   there when it's ready to announce.

### "Faculty want to change a published seminar's description."

They edit it on the event's own edit page; substantial changes come to
you under the **Changes** tab as **Pending review**. Compare the
current and proposed text and click **Approve & apply** or **Decline**.

---

## When to ask the Web Coordinator for help

- Adding a new PC member to the committee list (so they can access this
  admin).
- Anything that looks wrong or broken.
- Anything you'd like to do that this admin doesn't yet handle.
