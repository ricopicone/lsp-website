# Guest-Friendly Event Registration — Design (task #464)

**Date:** 2026-07-24
**Status:** Approved by Rico (brainstorming session)

## Problem

Many LSP events (special events especially, but also seminars and other types)
are open to guests, i.e. non-members. The current registration path is
unfriendly to them:

- The public event page shows a bare "Register →" button with no hint that
  non-members are welcome or that sign-in comes next.
- Clicking Register hits `@login_required` and lands on the login page, whose
  subtitle reads "Member services for the Lacanian School." A guest can
  reasonably conclude they cannot register.
- The "No account? Sign up" link exists and correctly preserves `?next`, but
  it is visually tiny and nothing explains that anyone may create an account,
  or that creating one does not make you a member.
- The site header shows only "Log in" to anonymous visitors — no signup path.

The plumbing already works end-to-end (signup is open, preserves `?next`,
returns the guest to the register form, and new accounts get role
`external`/"Auditor", which is exactly the guest pricing tier). The fix is
framing and messaging, plus one explicit per-event flag.

## Decisions (from brainstorming)

1. **Account required** — keep the account-based flow (no anonymous checkout);
   make it welcoming instead.
2. **Entry path** — keep the redirect to the login page but make it
   context-aware when `?next` targets an event registration. No interstitial.
3. **Guest signal** — a new explicit `Event.open_to_guests` flag (human
   control, per the do-not-over-automate principle), not derived from price
   tiers.
4. **General surfaces** — also soften the generic login subtitle, add a
   header "Sign up" link for anonymous visitors, and add a signup-page
   explainer.

## Design

### 1. Data model: `Event.open_to_guests`

- `BooleanField(default=True)` on `events.Event`, help text: non-members are
  welcome to register for this event.
- Migration defaults True for all existing events (accurate for the current
  program; PC/faculty switch off exceptions by hand).
- Exposed in Django admin and on the faculty edit form as a
  **non-reviewable** field — applies immediately, like `schedule_note` /
  `contact` / `record_video`; it is logistics, not content, so it skips the
  change-review dialog.
- **Messaging-only**: the flag controls page copy. It does not gate
  registration. Staff discretion (comps, offline payments, tier choice)
  stays intact.

### 2. Event page messaging (shared partial)

In `events/templates/events/_event_summary.html`, next to the Register CTA,
when the event is open for registration and `open_to_guests` is true:

- All viewers: "Open to non-members. Guests are welcome to attend."
- Anonymous viewers additionally: "You'll be asked to sign in or create a
  free account. You don't need to be a member."

The partial is shared by one-off event detail pages (special events, Days of
Assembly, working days, scholarly seminars) and seminar/reading-group
Workspaces, so both surfaces get the note from one change.

### 3. Context-aware login and signup

- Replace the stock `auth_views.LoginView` URL wiring with a thin subclass
  whose `get_context_data` inspects `next`: `resolve()` it; if it names
  `registrations:register` and the slug loads an event whose
  `is_public_now` is true, put the event in context as `register_event`.
  Any failure (garbage next, bad slug, draft event, unrelated URL) falls
  back silently to generic copy.
- `accounts.views.signup` gets the same resolution helper (shared function,
  e.g. `accounts/views.py: _event_from_next(request)` or a small helper in
  `events`), passing `register_event` to its template.
- `login.html` with `register_event`: heading "Sign in", subtitle
  "to register for [Event Title]". The signup path is promoted from a tiny
  footer link to a full-weight "Create a free account" button, with the
  line: "New to the School? Anyone can create a free account. Membership
  isn't required to attend."
- `signup.html` with `register_event`: heading "Create a free account to
  register for [Event Title]".
- The magic-link flow is untouched.

### 4. General auth surfaces (no event context)

- **Login subtitle**: "Member services for the Lacanian School." →
  "Sign in to the Lacanian School." The create-account option keeps its
  promoted weight even without event context.
- **Signup page explainer**: an account lets you register for events, pay
  online, and receive receipts. It doesn't make you a member of the School;
  membership is by application (link to the admissions/apply page).
- **Header** (`core/base.html`): anonymous visitors get a "Sign up" button
  beside "Log in".

### 5. Copy conventions

Member-facing site copy uses commas/periods, never em dashes
(`em-dash-prose-style` memory). All new copy above follows this.

### 6. Testing

- `open_to_guests` default true; present in admin and faculty edit form;
  edit-form change applies immediately (not routed through change review).
- Event page shows the guest note when flag on + registration open; hides it
  when flag off; anonymous viewers get the extra sign-in line, signed-in
  viewers don't.
- Login view: `?next` pointing at a register URL for a public event renders
  the event title; garbage / draft-event / non-register `next` renders
  generic copy.
- Signup view: same context behavior; existing `?next` round-trip continues
  to pass.
- Header: anonymous users see both "Log in" and "Sign up"; authenticated
  users see neither.

## Out of scope

- No-account guest checkout.
- Filtering/reordering price tiers shown to guests on the register form.
- Any enforcement tied to `open_to_guests`.
