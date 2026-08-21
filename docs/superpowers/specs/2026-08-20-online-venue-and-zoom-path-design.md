# An online event says where online: the in-site room, or somewhere else

Task #624. Gardner Bovingdon, teaching a seminar this term, asked whether the
site's video feature is meant for class meetings — he wants screen sharing and
breakout groups, and would rather stay on Zoom "to minimize technical snags."

## The problem

The honest answer to "can I use Zoom instead?" is *yes, but the site will fight
you about it*, and that was not documented anywhere because it was not known.

`Event.access_info` has always been able to carry an external meeting link, and
it is released to paid registrants on the event page, in the confirmation email,
and in the calendar feed. What is missing is any way to say that the external
link is *the* way in. Nothing records "online, but elsewhere":

- `EventProposal.LocationKind` offers `online_insite`, `in_person`, `hybrid`.
  There is no fourth option, so a seminar that meets on Zoom cannot be proposed
  as one.
- `Event.format` is `online` / `in_person` / `hybrid` — the axis is *whether*
  people gather in a room, never *which* online room.

The consequence is that an event with a Zoom link shows the member two doors,
one of which opens on an empty room:

- `events/templates/events/_event_summary.html` includes `_location.html` at
  line 101, which renders a **"Join the meeting room"** button for any event
  with `format != in_person`, gated only on the *global* `daily_enabled()`. It
  never consults `access_info`.
- The same template renders **"Your access details"** with the Zoom link at
  line 122.

The confirmation email is worse. `payments/emails.py:102` sets `room_url` on
`has_access and daily_enabled()` with **no format check at all**, so the "Join
the meeting room (in your browser, no app to install)" paragraph is mailed to
registrants of *in-person* events too. That is a live defect independent of this
task, and it is fixed by the same predicate.

And faculty cannot fix any of it themselves: neither `access_info` nor `format`
is on `EventEditForm` (`events/forms.py:166`). Only the Program Committee's form
and the Django admin can set a meeting link. The faculty guide's current "ask
the Program Committee" is accurate rather than lazy.

## Decisions

**The state is explicit, not derived.** The tempting cheap fix is to treat
"online event with non-empty `access_info`" as meaning "meets elsewhere" and
suppress the room on that basis. It is wrong, and the reason is hybrid: the
proposal mint already writes the venue address into `access_info` for a hybrid
event (`events/models.py:1581`), and a hybrid event wants the in-site room *and*
carries an address. A derived predicate would silently take the room away from
every hybrid event. This repeats the #532 finding directly — the bug there was
each surface re-deriving a fact instead of asking one predicate.

**But the guess is good enough to run once, at migration time.** Applied to
today's data, where it can be inspected before it lands and never fires again,
`format == online and access_info != ""` is exactly the set of events that mean
"we meet on Zoom." That is how #566 carried a members-only visibility across.

**Faculty own the venue; the Program Committee owns the format.** Whether an
offering gathers in a room, online, or both is a program-level fact the PC
publishes. *Which* online venue is a teaching decision belonging to the person
teaching. So `online_venue` and `access_info` join the faculty form and `format`
does not.

**The Workspace Meet tab stays.** The room belongs to the *workgroup*, not the
event, and a seminar's group uses it for ad-hoc meetings that are not the class.
Suppressing it because this term's class meets on Zoom would remove a facility
nobody asked to lose.

**Neither new field is reviewable.** `REVIEWABLE_FIELDS` protects the content
the PC approved — title, description, readings, fee. A meeting link was never
approved content and has no prior value to diverge from. Same reasoning as
`requires_faculty_approval` (#564) and `registration_eligibility` (#566).

## The field

`Event.online_venue`, a `CharField(max_length=20)` with choices:

    INSITE   = "insite",   "In the site's video room"
    EXTERNAL = "external", "External link (Zoom, etc.)"

defaulting to `INSITE`. It is orthogonal to `format` on purpose: a hybrid event
can meet in person *and* on Zoom, which a fourth `Format` choice could not
express without multiplying the choices.

When `format == in_person` the field is meaningless and simply never read.

## The predicate

One property, and every surface asks it:

    @property
    def uses_insite_room(self) -> bool:
        return (
            self.format != self.Format.IN_PERSON
            and self.online_venue == self.OnlineVenue.INSITE
        )

## Call sites

| Site | Now | After |
|---|---|---|
| `events/views.py` event context | passes `daily_enabled` | also passes `meets_insite = daily_on and event.uses_insite_room` |
| `_location.html` | gates the Join button and the "In your browser" line on `daily_enabled` | gates them on `meets_insite`; when external, points the reader at the access details below |
| `payments/emails.py:102` | `has_access and daily_enabled()` | `... and registration.event.uses_insite_room` |

The email change fixes the in-person defect as a side effect: an in-person event
is never `uses_insite_room`, so it stops being mailed a video-room link.

## The proposal form

`EventProposal.LocationKind` gains:

    ONLINE_EXTERNAL = "online_external", "Online — external link (Zoom, etc.)"

`event_format` maps it to `Format.ONLINE`. The mint's existing line —

    access_info = self.location if self.location_kind != ONLINE_INSITE else ""

— already carries `location` into `access_info` for the new kind with no change.
`location`'s help text is widened to say it holds the meeting link for an
external online proposal, and it stays **optional**: faculty proposing in the
spring rarely have next autumn's Zoom link, and the faculty edit form is where
they add it later.

## The faculty form

`access_info` and `online_venue` join `EventEditForm.Meta.fields`, gated by the
existing `can_edit_event` so a reading group's conveners get them too (#495).

`online_venue` needs `required = False` and a `clean_online_venue` coercing to
`INSITE`, because a choices-plus-default field on a ModelForm is required by
default and would break every POST that omits it — the standing
`new-modelform-field-is-required-by-default` trap, hit by both #566 and #486.

`event_edit_confirm.html` re-posts every field as a hidden `<textarea>`, which a
TextField and a `<select>` both survive; only checkboxes need the explicit
exception list at line 36. No change is needed there, but a test pins that both
values survive the re-post, because a silent revert would be invisible (#566).

## Breakout rooms

Daily exposes `enable_breakout_rooms` as a room property. It requires Daily
Prebuilt, which is what `video/` runs, and it requires an *owner* to be in the
call to create the rooms. Daily documents it as **beta**.

It is added to `video/services.py::_desired_properties`, which #475 made the
single source of truth that `ensure_room` reconciles against the live room on
next join — so existing rooms pick it up without a backfill. `is_owner` already
resolves to `can_edit_event` / `is_workgroup_lead`, so faculty and conveners get
the control and attendees do not.

Screen sharing needs no change: Prebuilt enables it by default and
`_desired_properties` never disabled it.

## The migration

Two operations:

1. `AddField` for `online_venue`, default `insite`.
2. A data migration setting `online_venue = "external"` where
   `format == "online" AND access_info != ""`, with a no-op reverse.

Nothing else moves. No event loses access, no registration is re-priced, no mail
is sent.

## Documentation

The faculty guide's "Access details, the room, and recordings" section
(`content/pages/guides/faculty.md:214`) is rewritten to cover both paths:

- **The site's room** — no link to send, the Join button appears for registrants
  when the meeting begins, screen sharing and breakout rooms are there, hosts
  moderate, recording is opt-in and lands in Works.
- **Zoom or another service** — set the venue to the external link and paste it
  in; it reaches paid registrants on the event page and in their confirmation
  email; the site stops offering its own room.
- **What you give up** by leaving: no presence, no Join button, and no recording
  pipeline.

Per `member-facing-copy-says-what-not-why`, the copy says what happens, not why
the code does it. Breakout rooms are named as new and beta.

## Testing

- `uses_insite_room` across the `format` × `online_venue` truth table.
- Event page: an external online event shows the access details and **no** Join
  button and no "In your browser" line; an in-site one is unchanged.
- Confirmation email: no `room_url` when external; no `room_url` for an
  in-person event (the regression this uncovered); `room_url` present for an
  in-site online event.
- Faculty edit form saves both fields; both survive the confirm-dialog re-post.
- Neither field is in `REVIEWABLE_FIELDS`.
- The mint maps `ONLINE_EXTERNAL` to `format=online`, `online_venue=external`,
  `access_info=location`.
- The data migration's carry-across, both directions.
- `_desired_properties` includes `enable_breakout_rooms`.

## Not doing

- **Suppressing the Workspace Meet tab** for an external event — the room is the
  group's, not the term's.
- **Letting faculty change `format`.** In-person vs online is the PC's to
  publish.
- **A hybrid-external proposal choice.** `LocationKind` gains one option, not
  two; a hybrid event that also meets on Zoom is set on the event afterwards.
- **Provisioning suppression.** An external event still has a workgroup room
  standing behind it; `event_video_preflight` stays read-only by default and is
  not taught about venues in this task.
- **Migrating anyone off Zoom.** Gardner's answer is "yes, stay on Zoom, and
  here is how" — the site accommodates the choice rather than arguing with it.
