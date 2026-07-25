# Coming up: pin upcoming special events to the top (task #461)

## Problem

The landing page's **Coming up** section lists the four soonest published
events, ordered by `start_date`. In September the annual program's seminars all
begin within days of each other, so a one-off special event scheduled in the
same stretch is pushed below the fold, or off the list entirely, by events that
are neither urgent nor time-limited — a seminar's start date is the least
interesting thing about it, while a special event *is* its date.

A second problem surfaced in the same query: the landing list filters only on
`published=True`. It never applies the members-only visibility gate that
`/events/` applies (`events/views.py:event_list`), so a `members_only` event's
title, type, and dates are rendered to anonymous visitors on the public front
page.

## Rule

Reserve up to **two pinned slots** at the top of Coming up, drawn from
**standalone-type** events — every `Event.Type` *not* in
`Event.ANNUAL_PROGRAM_TYPES`, i.e. Special event, Day of Assembly, Working Day,
Scholarly Seminar Series — whose `start_date` falls within the **next two
months**.

Pins are ordered *true `special_event` first, then by `start_date`, then
`title`*. A genuine special event therefore always takes the top slot; the
second slot goes to the next-soonest standalone event, whatever its type (a
second special event included).

The list total stays **four**. Remaining slots fill chronologically exactly as
before, with the pinned events de-duplicated out so nothing appears twice. When
no standalone event falls in the window, the section renders exactly as it does
today.

Scope is the landing page only. `/events/` already excludes the annual-program
types, so nothing is buried there; `/program/` is a program index, not a
what's-next list.

## Design

### `events/upcoming.py` (new)

One public function holds the whole rule:

```python
landing_events(user, limit=4) -> list[Event]
```

- Base queryset: published events that either start today or later, **or** are
  seminars that started within the last 31 days and haven't ended — the
  existing late-registration grace, moved unchanged from `core/views.py`.
- Members-only gate: unless `accounts.permissions.is_lsp_member(user)`, the
  queryset is narrowed to `visibility=PUBLIC`.
- Pins: the base queryset restricted to `start_date <= today + 2 months` and
  excluding `ANNUAL_PROGRAM_TYPES`, annotated with a
  `Case(When(event_type=SPECIAL_EVENT, then=0), default=1)` sort key, ordered
  `(that key, start_date, title)`, sliced to two.
- Remainder: the base queryset excluding the pinned primary keys, sliced to
  `limit - len(pinned)`.
- Each pinned instance carries a transient `pinned = True` attribute for the
  template. Returns `pinned + remainder`.

Two queries; the pins cannot be found by slicing the chronological list first,
since being outside the top four is the condition the feature exists to fix.

Module constants: `PIN_WINDOW_MONTHS = 2`, `MAX_PINNED = 2`,
`LATE_SEMINAR_GRACE_DAYS = 31`. The two-month window uses
`dateutil.relativedelta` (already a dependency, used by the recurrence helper)
so it means calendar months, not 60 days.

### `core/views.py`

`landing()` drops its inline `upcoming` query and calls
`landing_events(request.user)`. No other context changes.

### `core/templates/core/landing.html`

A pinned row's type badge switches from the primary tint to the accent tint
(`bg-accent/15 text-accent border-accent/25`) — no added text. The badge already
names the type ("Special event"), and the accent tone explains why a later date
sits above an earlier one. The rest of the row markup is untouched. Both class
sets are written literally in the template so the Tailwind v4 scanner keeps
them.

## Testing

`events/test_upcoming.py`:

- A special event that falls outside the chronological top four is pinned to
  position one.
- A special event more than two months out is not pinned.
- With one special event and one Working Day in the window, the special event
  takes slot one and the Working Day slot two.
- Seminars, reading groups, and cartels are never pinned.
- A pinned event does not also appear in the chronological remainder.
- The list never exceeds four items.
- `members_only` events are hidden from anonymous visitors and from
  authenticated non-members, and shown to members — in both the pinned and the
  chronological positions.
- The seminar late-registration grace still surfaces a seminar that began
  within the last 31 days.

The existing landing-page tests in `core/tests.py` stay green unchanged.

## Non-goals

- No new model field, admin toggle, or per-event "pin me" switch. The rule is
  derived from type and date; if the school later wants manual control, that is
  a separate decision.
- No change to `/events/`, `/program/`, or the calendar feed.
- No change to the list length (four) or to the section's copy.
