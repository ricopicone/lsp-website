# The PC creates every standalone event type (task #756)

## Problem

The Program Committee chair asked how to create a Day of Assembly or a
Working Day. The only answer was the Django admin. The rest of the site
already supports all four PC-organized types (`Event.PC_OWNED_TYPES`:
special event, Day of Assembly, Working Day, Scholarly Seminar Series). They
get the PC's workgroup, a meeting room of their own, calendar and "My
events" listing, and presenters through `member_speakers`. What was missing
was a way to create them:

- **+ New special event** (`program_admin_special_event_new`) pins the
  proposal form's type to `special_event`, and `EventProposal.event_type`
  offers only seminar, reading group and special event.
- The Proposals tab's **Special events** list and its two row actions
  (publish, open/close registration) filter on `event_type=SPECIAL_EVENT`,
  so a Day of Assembly made in Django admin had no place in the PC's admin.

The pc-admin guide said so outright: "the other standalone types are set up
in Django admin."

## Design

Widen the special-event path to the four PC-owned types. Don't add a second
path.

1. **`EventProposal.event_type`** gains Day of Assembly, Working Day and
   Scholarly Seminar Series (a migration that only changes choices).
   `PROPOSABLE_TYPES` stays as it is: member proposals are still
   seminar / reading group / special event.
2. **`EventProposalForm`** narrows `event_type` to `PROPOSABLE_TYPES` by
   default, so the member's propose and edit forms can't offer the new
   types even though the model now allows them. This is the "visible only
   to the PC" requirement, enforced where the form validates the POST and
   not only where the page renders it.
3. **Direct-create** (`program_admin_special_event_new`, still gated by
   `_is_pc_or_staff`) offers all four PC-owned types in `Event.Type`
   order, with special event selected by default. `approve()` needs no
   change, because every non-offering path in it (date → first Session,
   price tier, provenance link to the PC workgroup, published iff dated) is
   already type-neutral.
4. **The Proposals tab list** becomes **Standalone events** and covers
   every PC-owned type, with a type badge on each row. The publish and
   registration endpoints accept any PC-owned type. Program events are
   still refused, since their visibility cascades from the Program (#532).
5. **The form's JS** treats every one-off type the way it treats
   `special_event` (date/time, TBD, speakers, honoraria). This is a single
   normalization step in `sync()`, so no `data-types` attribute has to list
   four types.

URL names keep their `special_event` spelling. Renaming them changes
nothing a user sees and would break any open tab.

Deliberately unchanged: `REVIEW_LOOP_TYPES` (a PC-created event isn't
approved content that faculty might drift from), and `upcoming.py`'s
special-event-first pin order.

No flag. No backfill. Days of Assembly already created in Django admin
simply appear in the list.
