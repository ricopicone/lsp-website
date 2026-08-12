# Registration eligibility: members only, or members and guests

Task #566. Design date 2026-08-12.

## The problem

`Event.open_to_guests` says, in its own help text, that it "does not restrict
who can register". It is a note toggle: ticking it prints *"Open to
non-members. Guests are welcome to attend."* on the event page and nothing
else. There is no way to say the opposite thing and have it hold. Every
registration gate the site has is about the *registrant's* obligations
(the tuition decision) or the *event's* state (`status == OPEN`,
`is_public_now`); none is about whether this event is for members.

The ask is that the option have teeth: an event declares who may register,
members only or members and guests, and the site enforces it.

Note the flag has never been used. All 28 events on prod carry
`open_to_guests=True, visibility=public` — the default. So the enforcement is
new behavior for nobody until someone chooses it, and the data migration
cannot change what any live event does.

## Decisions

Four, taken with Rico on 2026-08-12.

**A guest is anyone who is not `accounts.permissions.is_lsp_member`.** That
predicate already answers "is this person a member of the school?" everywhere
else, and it is deliberately wider than a role check: it admits Django staff,
the LSP Staff designation, and serving committee members whatever their role,
and it excludes the resigned and removed standings. Three `Profile.Role`
values fall outside it — Auditor (`external`), Student, and Prospective
Applicant — and all three are guests here. The rejected alternative was
treating only Auditor as a guest, which would have meant a second predicate
disagreeing with the first about who belongs to the school.

**A pricing code addressed to a named person is the escape hatch.**
`PricingCode.restricted_to_user` already exists. A guest holding a live,
unspent code restricted to them may register for a members-only event: the
faculty member who minted it made the decision, which is what §4.1 asks for.
An *unrestricted* code does not open the door, because a code that can be
forwarded is not a decision about a person. This narrows the task #495
scholarship recipe on members-only events only — "mint an unrestricted 1-use
code" becomes "mint it restricted to them", one extra field on a form faculty
already use. Rejected: a code box on the blocked page (any forwarded code
admits any stranger), and staff-comp-only (faculty lose the self-serve route).

**The field is replaced, not retrofitted.** `open_to_guests` is named for
messaging, and that name is a fair part of why it never grew teeth. It becomes
`registration_eligibility`, a two-choice field labelled in Rico's own words.

**It stays independent of `Event.visibility`.** The two answer different
questions — visibility is who can *see* the page (it hides an event from
anonymous visitors on public listings; a signed-in auditor still sees it),
eligibility is who can *register*. Every combination is coherent, including
the one that looks odd: an event hidden from search engines but open to any
account holder. As it happens `visibility` is not on either edit form (it is
Django-admin only), so the two never appear side by side in the faculty or PC
UI and no wording has to distinguish them there. What does change is the event
page's guest note, which today reads
`open_to_guests and visibility != "members_only"`; that conjunction was
covering for the flag's lack of meaning and goes away — eligibility alone
drives the note.

## The field

```python
class RegistrationEligibility(models.TextChoices):
    MEMBERS_AND_GUESTS = "members_and_guests", _("Members and guests")
    MEMBERS_ONLY = "members_only", _("Members only")

registration_eligibility = models.CharField(
    max_length=20,
    choices=RegistrationEligibility.choices,
    default=RegistrationEligibility.MEMBERS_AND_GUESTS,
    verbose_name="Who can register",
    help_text=(
        "Members only limits registration to members of the School. "
        "Members and guests lets anyone with a free account register, and "
        "shows a guests-welcome note on the event page."
    ),
)
```

Default `MEMBERS_AND_GUESTS`, matching today's `open_to_guests=True` default:
the school stays open unless someone says otherwise, and no existing event
changes behavior. Three migrations in one file — add the field, copy
`open_to_guests` across (`True → members_and_guests`,
`False → members_only`, reversible), drop the boolean.

`max_length=20` fits `members_and_guests` (18) with room to spare.

## The predicate

One function, in `registrations/permissions.py` beside
`can_administer_registrations`:

```python
def eligibility_block_reason(user, event) -> str | None:
```

It returns a member-facing reason, or `None` to allow — the shape
`registrations.views._tuition_block_reason` already uses, so the view gains a
second guard of exactly the same form rather than a new pattern. It allows,
short-circuiting in this order:

1. the event is `members_and_guests`;
2. `is_lsp_member(user)`;
3. the user holds a live, unspent `PricingCode` for this event with
   `restricted_to_user=user` — not expired (`valid_until`), and either
   `max_uses is None` or `uses_remaining > 0`;
4. `events.permissions.can_edit_event(user, event)` or
   `event.is_presenter(user)` — an outside speaker with a linked login
   (task #463) must never be told "members only" about their own event.

Only step 1 runs for the overwhelming majority of page loads, and steps 3–4
only for a non-member on a restricted event, so the added query cost lands
solely on the case that needs it.

The reason string names the restriction and the two routes onward — the
school's application, and asking the event's faculty for a code:

> Registration for this event is limited to members of the Lacanian School.
> If you have been invited to attend, ask the event's faculty for a
> registration code addressed to you.

## Enforcement

**`registrations.views.register_for_event`** is the one enforcement point,
because it is the one place a member-facing registration is created (the other
`Registration.objects.create` in that module is the tuition-covered
short-circuit inside the same view, downstream of the guard). The check goes
immediately after the existing tuition gate and renders a new
`registrations/blocked_members_only.html` with `status=403`, modelled on
`blocked_tuition.html`: the event title, the reason, and a link to
`admissions:apply_start`.

Placing it after the already-registered short-circuit is deliberate. A guest
who registered while the event was open and is then restricted keeps their
registration and can still reach its confirmation page; nothing unwinds, and
un-registering them is the registrar's call, not a side effect of an edit
(the task #485 precedent — staff paths never bill or unbill silently).

Staff paths are untouched and remain the manual override: the registrar
console's comp and approve actions, the Django admin, and
`registrations.services.comp_registration` all bypass the gate, because each
is a human deliberately acting.

## What a visitor sees

**The event page** (`events/_event_summary.html`). The Register CTA is
replaced, for a signed-in user the gate would block, by a plain note carrying
the same reason and the application link. A button that leads to a 403 is
worse than no button. The fee table stays: what an event costs is public.

Anonymous visitors are the case to get right, because the site cannot tell a
member who has not signed in from a stranger. They keep the Register button —
it leads to login, where a member signs in and proceeds — under a note reading
*"Registration for this event is limited to members of the School."* No one is
turned away who belongs, and no one is lured into an account under a false
impression.

**The login and signup pages** (task #464's funnel). `_register_event_from_next`
already hands both templates the event. Two lines currently promise something a
members-only event cannot honor: login's *"Anyone can create a free account.
You don't need to be a member to attend"* and signup's framing of the account
as the way in to this event. Both become conditional on the event's
eligibility; for a members-only event they say instead that registration is
limited to members and point at the application. The free-account button stays
— an account is still worth having, and a guest may hold a code — but it stops
claiming it will get them into *this* event.

**The guests-welcome note** on the event page now keys off
`registration_eligibility == members_and_guests` alone.

## Forms and the change-review dialog

The field replaces `open_to_guests` in `EventEditForm.Meta.fields` (faculty)
and `ProgramEventForm.Meta.fields` (PC), with a
`forms.Select(attrs={"class": "select select-bordered"})` widget in place of
the checkbox, and the corresponding block in `event_edit.html` and
`program_admin/event_form.html` becomes a labelled select.

It stays **out of `REVIEWABLE_FIELDS`**, as `open_to_guests` was. Change review
protects the content the Program Committee approved; who may register is an
operational decision the faculty and the PC make directly.

That non-reviewable status routes it through `event_edit_confirm.html`'s
re-post, which carries each non-reviewable field forward as a hidden
`<textarea>`. A `CharField` with choices survives that intact — the textarea
holds `members_only` and the field validates it — which is precisely why the
checkbox fields (`record_video`, `tuition_covers`) need their special case
there and this one does not. A test pins it, because the failure would be
silent: an eligibility change quietly reverting on any event that routes
through review.

## Documentation

- The faculty guide (`core/docs/faculty-guide.md`) gains the narrowed recipe:
  to admit a specific non-member to a members-only event, mint the code
  restricted to them.
- The registrar guide (`core/docs/registrar-guide.md`) notes that comping is
  unaffected by eligibility.
- `docs/event-video-rehearsal.md` references `open_to_guests` in its mirror-
  event checklist and is updated to the new field.

## Testing

- The field defaults to `members_and_guests`; the data migration maps both
  boolean values.
- `eligibility_block_reason` returns `None` for: any user on an open event; a
  member; a guest holding a restricted code; a guest who is the event's
  presenter or editor. It returns a reason for: an auditor, a student, a
  prospective applicant, a resigned member, and a guest whose restricted code
  is spent or expired, and for a guest holding an *unrestricted* code.
- `register_for_event` returns 403 and the block template for a blocked guest;
  200 for a member; 200 for a guest with a restricted code.
- A guest who registered before the flip keeps their registration and reaches
  its confirmation page.
- The event page hides the Register CTA for a blocked signed-in guest, keeps
  it for anonymous visitors, and shows the guests-welcome note only on a
  `members_and_guests` event.
- The change-review re-post preserves a `members_only` value.
- Both edit forms expose the field, and it is absent from `REVIEWABLE_FIELDS`.

## Not doing

- **No per-role eligibility matrix.** Two options, as asked. A tier already
  prices per audience; eligibility is a single line.
- **No unwinding of existing registrations** when an event is restricted.
- **No flag.** The behavior is reversible by setting the field.
- **Not touching `visibility`**, and not adding it to the edit forms.
- **No enforcement of tier audiences.** Any registrant can still select any
  tier on the form — an honesty system that predates this task and is
  unchanged by it.
