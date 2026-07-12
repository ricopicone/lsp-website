# In-app schedule (session) editor for standalone events

*Task #421 follow-on. Design date: 2026-07-12.*

## Problem

A standalone one-off event (special event, Day of Assembly, Working Day,
Scholarly Seminar) stores its date/time as one or more **`Session`** rows
(`start_at`, `end_at`, `location`) plus the `Event.start_date` / `end_date`
columns. Everything *else* about such an event is editable in-app on the faculty
edit page (`events:edit`) — title, description, readings, fee, contact — but the
**date/time is not**. Changing when the event happens requires Django admin.

Faculty, the Programming Committee, and LSP staff should be able to edit the
schedule in-app. They already have edit rights (`can_edit_event` = event
faculty, Programming Committee, LSP Staff, or Django staff) — the gap is purely
that the fields aren't exposed.

## Goal

An in-app **multi-session schedule editor** on `events:edit` for standalone
one-off event types: list the event's sessions, edit each one's date / start /
end / location, add a session, remove a session — saved together.

### Non-goals

- Annual-program types (seminar, reading group, cartel): their schedule is a
  recurring `MeetingSeries` generated + managed through the workgroup meetings
  layer. Out of scope; the editor does not appear for them.
- Per-session pricing, registration, or notifying registrants of a date change
  — a possible follow-up, not this change.

## Approach — an isolated session formset with its own Save

The editor is a **separate form + view**, not folded into the content
`EventDescriptionForm`. Reason: the `event_edit` change-review path applies
non-reviewable changes with a generic `setattr(event, f, …)` loop that assumes
every field is an `Event` model field; sessions are a *different* model, so
threading them through that form would break it. Isolation also keeps the
schedule editor independently testable.

This matches the existing external-speaker formset pattern in
`propose_event.html` (management form + stacked rows + a `<template>` cloned by
a small "+ Add" script + a `DELETE` checkbox per row).

## Components

### Form — `SessionScheduleForm` (ModelForm on `Session`)

`start_at` and `end_at` are two independent `datetime-local` inputs (not a
shared date + two times): once times are entered in the editor's **own
timezone**, a session's start and end can fall on different calendar dates, so
each carries its own date. This also makes the form identical to the proven
`WorkgroupMeetingForm`.

- `Meta.fields = ("start_at", "end_at", "location")`, `datetime-local` widgets,
  `input_formats = ["%Y-%m-%dT%H:%M"]`, all `required=False` at field level.
- Django localizes the naive input to the request's **active timezone** (the
  user's `Profile.timezone`, via `TimezoneMiddleware`) — the same behavior as
  every other datetime input in the app. No hardcoded Pacific.
- `clean()`: a fully-blank extra row is dropped by the formset; a partial row
  errors ("give both a start and an end"); `end_at <= start_at` errors.

The edit page shows a "Times are in your timezone (`<tz>`)" note via the
`user_tz_name` tag, so the input tz is never ambiguous.

### Formset — `SessionScheduleFormSet`

`inlineformset_factory(Event, Session, form=SessionScheduleForm, extra=1,
can_delete=True)`. Bound with `instance=event`, `prefix="sessions"`. The FK to
the event is set automatically; blank extra forms are ignored; `DELETE` removes
existing sessions.

### View — `event_edit_schedule(slug)`

- `@login_required`, `@require_POST`.
- `get_object_or_404(Event, slug=…)`; `HttpResponseForbidden` unless
  `can_edit_event`; `Http404` unless `event.event_type in Event.PC_OWNED_TYPES`
  (the standalone one-off set).
- Bind the formset; on valid, inside `transaction.atomic()`: `formset.save()`,
  then **re-sequence** sessions by `start_at` (write `sequence = 1..n`) and
  **sync `Event.start_date` / `end_date`** to the earliest / latest session
  dates (Pacific). Redirect to `events:edit` with a success message.
- On invalid: re-render `event_edit.html` with the bound (error) formset plus a
  fresh content form.

`event_edit` (GET) also builds an unbound `SessionScheduleFormSet(instance=event,
prefix="sessions")` and a `show_schedule_editor = event.event_type in
Event.PC_OWNED_TYPES` flag, and passes both to the template.

### URL

`events/<slug>/edit/schedule/` → `event_edit_schedule`, name
`events:edit_schedule`.

### Template — a "Schedule" section on `event_edit.html`

Rendered only when `show_schedule_editor`. A `<form>` posting to
`events:edit_schedule`, containing the formset management form, one **stacked
card per session** (labeled Date / Start / End / Location, a **Remove** control
wired to the row's `DELETE` checkbox), a hidden `<template>` empty-form, an
**+ Add session** button, and a **Save schedule** button. A small script clones
the template (replacing `__prefix__`, incrementing `TOTAL_FORMS`) for Add, and
checks `DELETE` + hides the card for Remove — mirroring the speaker-formset
script. If the event has no sessions yet (was date-TBD), the editor shows one
blank card; saving it creates the session and makes a TBD draft publishable.

## Data flow

Split date/time fields → Pacific-aware `start_at` / `end_at` on each `Session`
→ formset create/update/delete → re-sequence + sync `Event.start_date/end_date`.
Times are stored tz-aware (UTC in the DB) and always entered/displayed as
Pacific.

## Edge cases

- **Blank extra card** → ignored (not saved).
- **Partial row** (date but no times, or end ≤ start) → validation error,
  re-render with messages; nothing saved (atomic).
- **Remove all sessions** → allowed; `Event.start_date/end_date` left at their
  current values (no sessions to derive from). The event simply has no schedule
  shown until one is added again.
- **Non-standalone event** (seminar/reading group/cartel) → editor not shown;
  the POST view 404s, so it can't be driven by hand.
- **Non-editor user** → `HttpResponseForbidden` (GET page already gated).
- **Multi-session** (e.g. a Scholarly Seminar Series) → every session is a card;
  order in the DB follows `start_at` after re-sequencing.

## Testing (`events/test_program_admin.py` or a new `events/test_schedule_editor.py`)

- Editor renders on a special event's edit page (cards for existing sessions);
  does **not** render for a seminar.
- Editing a session's date/time updates its `Session.start_at/end_at` and the
  `Event.start_date`.
- Adding a session creates a new `Session`; the count goes up and dates sync.
- Removing a session (DELETE) deletes it; re-sequencing holds.
- Setting a date on a previously date-TBD special event creates its first
  session (enabling publish).
- `end_time <= start_time` → error, nothing saved.
- Non-editor → 403; non-standalone type → 404.
