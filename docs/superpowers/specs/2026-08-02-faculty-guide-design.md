# Faculty guide: running a seminar or reading group (task #495)

**Date:** 2026-08-02
**Status:** approved, ready to implement

## The question

A faculty member asked:

> how should I deal with the issue of payment codes in case I want to extend a
> discount or scholarship to non-LSP members who may need a reduced fee?

The mechanism already exists — `events.PricingCode`, minted from the faculty
tools panel (PROG-8 / REG-17) — so the answer is a documentation gap, not a
missing feature. Nothing on the site tells faculty what those tools do, and the
one field that answers the question directly ("Restricted to user") is a bare
select over every account in the database, labelled by email.

The deliverable is a **Faculty Guide** in `/guides/`, plus the two small code
changes that keep it honest.

## Decisions

**One guide, not two.** Seminars and reading groups share the whole surface:
the same Workspace tab, the same roster, the same pricing codes, the same
review loop on edits. The differences are few (who runs it, and how it was
approved) and read better as a note inside one guide than as two documents that
drift. Slug `faculty`, title "Running a seminar or reading group", listed after
the member-facing `seminars` guide so the pair reads as two sides of one thing.

**Listed publicly, like every other guide.** No new audience-gating machinery.
There is nothing confidential in it, and a member who wonders how their seminar
is run may as well be able to read it.

**No walkthrough checklist.** The guides layer supports one (`checklist:` in
frontmatter), but every tool this guide describes lives on a single tab. A
checklist would be ceremony.

## What the guide says

The organising frame is **what is yours to decide and what isn't**, because
that is what the original question actually turns on. Faculty own the event's
public content, the roster, and *per-person* pricing. The Programming Committee
owns the listed fee and its price tiers (built from the approved proposal),
publication, opening and closing registration, `access_info`, and the faculty
list — all of them fields on the PC's program-admin form
(`events.forms.ProgramEventForm`), not on the faculty edit form
(`events.forms.EventEditForm`). The treasurer owns refunds and offline
payments. A faculty member who knows that boundary can tell, unprompted, which
of their questions has a self-service answer.

Sections:

1. **What's yours, what isn't** — the boundary above.
2. **Where your tools are** — seminars and reading groups: the Workspace
   **Roster** tab (`/groups/<slug>/?tab=roster`). One-off events: **Faculty
   view** on the event page.
3. **Editing your event page** — schedule note, contact, CE, guests-welcome
   apply immediately; title / description / readings / fee note on an approved
   event route through the certify-or-submit dialog (#295): minor is adopted
   now, substantial waits in the PC queue.
4. **Who's registered** — the roster table and its statuses, the CSV, and the
   pending-approval strip on events that require faculty approval.
5. **Fees, discounts, and scholarships** — the heart of it:
   - where the listed price, sliding scale, and covered-by-tuition come from;
   - the three code modes (percent off / fixed amount / sliding-scale floor),
     with uses, expiry, and restrict-to-one-person;
   - **an LSP member:** mint a code restricted to them, one use, send it;
   - **someone outside the school:** they need a free account to register at
     all, so either mint a one-use unrestricted code and send it (this works
     before they have signed up) or have them sign up first and restrict it to
     them;
   - **a fixed amount of $0 is a full scholarship** — the registration
     confirms on the spot with no checkout (`_create_registration` short-
     circuits a zero resolution to PAID);
   - what a code cannot do: change the listed fee, or refund someone who has
     already paid (the treasurer's call).
6. **Reading groups** — convener-led rather than faculty-led; everything above
   still applies to you.
7. **Access details, the meeting room, recordings** — short, with pointers.
8. **Who to ask** — Programming Committee, treasurer, registrar.

The guide is member-facing site copy, so it uses commas where in-repo prose
would use em dashes (the 2026-07-06 style exception).

One line is added to `events/templates/events/_faculty_tools.html` linking the
panel to the guide, so the explanation sits where the question gets asked.

## The convener gap

`can_edit_event` (`events/permissions.py`) gates the whole faculty tools panel
— roster, CSV, pending approvals, *and the mint-a-code form* — on Django staff,
the LSP Staff designation, `Event.is_faculty`, `Event.is_presenter`, or
Programming Committee membership. `Event.is_faculty` reads serving
**FACULTY**-role memberships on the event's workgroup.

When the PC approves a **reading group** proposal, its conveners are added as
**ORGANIZER**, not FACULTY (`EventProposal.approve`), deliberately: "reading
groups are organizer-led, not faculty." Such a convener therefore fails
`can_edit_event`, and `workgroups/views.py` only appends the Roster tab when
`can_edit_offering` — so they would see no tab at all, and could not mint a
code for their own group.

This is latent rather than live: the one reading group on production,
`freud-reading-group-2026-27`, carries its convener as FACULTY (verified
2026-08-02), because it predates the proposal route. The next reading group
approved through the proposal flow would hit it.

**Fix:** for a seminar or reading group with its own workgroup, `can_edit_event`
consults `workgroups.permissions.is_workgroup_lead(user, event.workgroup)` — the
task #480 lead primitive, which already knows chair / co-chair / faculty /
organizer. Faculty and conveners then resolve through one predicate instead of
two spellings of the same idea, and the guide can honestly say "you" throughout.

Scoped to those two event types on purpose:

- **Special events and the other PC-organized types share the Programming
  Committee's own workgroup.** Asking `is_workgroup_lead` there would be asking
  who leads the PC, which the existing PC-membership clause already covers more
  precisely.
- **Cartels** are in `ANNUAL_PROGRAM_TYPES` too, but they are member-led by
  design and are not what this guide is about. Leaving them out changes nothing
  for them today.

On an offering workgroup there is no attached `Committee`, so
`is_workgroup_lead`'s school-officer branch returns nothing: no President or
Vice President gains a seminar's roster by way of this change.

## The mint form

`PricingCodeForm`'s `restricted_to_user` is `ModelChoiceField` over the default
`User` queryset: every account, in no particular order, labelled by
`User.__str__` (bare email), including never-verified signups. That is the
exact field a faculty member reaches for when extending a scholarship to a
named person.

`__init__` now:

- orders the queryset by last name, first name, email;
- excludes never-verified signups — `is_active=False` with no
  `email_verified_at`, the same pair `purge_unverified_signups` treats as a bot
  row (task #471). A deceased member's account is deactivated but *has* a
  verification stamp, so this never hides a real person;
- labels each option "Name (email)", falling back to the email alone when the
  account has no name;
- carries help text: blank means anyone with the code may redeem it, and
  someone outside the school needs a free account before they can be picked
  here.

No schema change, no migration.

## Testing

- The guide loads at `/guides/faculty/` and its card appears on `/guides/`.
- `can_edit_event` is True for a serving ORGANIZER on a reading group's
  workgroup, and still False for a plain registrant on the same event.
- The Workspace shows that organizer the Roster tab with the mint form on it.
- `PricingCodeForm`'s person picker excludes an unverified signup, includes a
  verified member, and labels by name.

## Out of scope

A note/label field on `PricingCode` and a redemption view ("was the scholarship
taken up?") would both help, and neither is needed to answer the question. They
are a separate task if the treasurer or faculty ask for them.
