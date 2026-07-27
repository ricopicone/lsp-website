# Direct admission — onboarding a member who never applied on the site

**Task #476.** Design date 2026-07-27.

## Problem

The site admits members well when they apply through it. `admissions/` runs the
whole intake — apply, acknowledge, two interviews, Meeting of the Analysts
decision — and `admissions.services.accept_application()` is a real onboarding
moment: it records the membership change (role, standing, tenure timeline), sets
the formation background, and sends the `decision_accept` letter, which tells the
new Precandidate to choose an advisor, points at the formation guidelines, the
analyst-availability page, the members-only documents, the profile editor, and
My LSP.

None of that is reachable for a member admitted *outside* the site. `Application`
is a `OneToOne` on a `User` and requires a letter of intent, so the coordinator
cannot retro-create one, and no other path reuses any of the acceptance work.
Today, admitting such a member means assembling it by hand across four surfaces:

| Step | Where it lives today |
|---|---|
| Create the account | Django admin, or `manage.py import_users` |
| Role + standing + effective AY | `/admin-tools/board/membership/` (Board-gated; existing accounts only) |
| Formation background | `/admin-tools/meeting-of-analysts/backgrounds/` |
| `year_joined` | profile editor / Django admin |
| The welcome letter | nothing — `decision_accept` is bound to an `Application` |
| Dues charge | treasurer → Sync charges |

Nothing ties the steps together, nothing records that the person was onboarded,
and the member gets no email at all. Two or three members accepted recently are
in exactly this position (they have no accounts, and they have already been
welcomed by hand over email).

## What we're building

A **direct-admission** form in the Web Coordinator's admin that creates the
account and runs the same admission the application path runs, plus one shared
service so the two routes cannot drift.

### 1. Placement and gating

The form lives at `/admin-tools/web-coordinator/admit/`, gated by
`staff_role_required(StaffRole.WEB_COORDINATOR)` (superusers pass, as with every
panel), and is reached from a section card on the Web Coordinator admin landing.

It is deliberately **not** in the Applications Coordinator's console. That
console is the application process; a second admission button inside it would
invite the coordinator to reach for the shortcut instead of deciding the
application in front of them. Keeping direct admission in a different role's
admin means the two never appear side by side.

The page is titled **"Admit a member without an application"** and opens with a
note: this is only for members admitted outside the site — accepted before the
application process moved here, or by another route. Anyone who applied on the
site is admitted from their application, in the Applications Coordinator's
console.

### 2. One shared admission service

`admissions/services.py` gains:

```python
def admit_member(user, *, track, background, effective_ay, by, note=""): ...
```

holding what acceptance *means*: `record_membership_change` (role from
`Application.ADMIT_ROLE[track]`, standing ACTIVE, tenure timeline) and
`formation.background.set_background(...)`.

`accept_application()` is refactored to call it, keeping only what is
application-specific: status, `decided_at` / `decided_by`, the decision note, and
the decision notification.

This is the point of the design. The two routes cannot drift, because there is
one function that admits a person. The tenure note differs by route —
`"Admitted via application (Analyst formation)."` versus `"Admitted directly by
the Web Coordinator — no site application."` — so the membership timeline records
how each member came in.

### 3. The form

Fields: email, first name, last name, track (Analyst / Scholar formation),
background (clinical / academic), effective AY (defaults to the current AY),
optional note, and the send choice (§4).

On submit it creates the `User` with an **unusable password** — `import_users`'
convention, and password reset is the intended way in, since
`ReplyToPasswordResetForm` deliberately drops Django's `has_usable_password`
filter so imported members are reachable. It then stamps `Profile.year_joined`
from the effective AY and `Profile.email_verified_at`.

That stamp matters. `purge_unverified_signups` deletes `is_active=False` accounts
with a null `email_verified_at`, and the invariant since task #471 is that a null
means "self-signup that never confirmed" and nothing else. A staff-vouched
account must not read as an unconfirmed bot row — the same reasoning that
grandfathered every pre-existing account in `accounts/0042`.

**Existing-account handling.** If the email already belongs to an account:

- **with an `Application` row** — refuse, and link to that application. Open
  ("this person applied on the site; decide it there"), already decided
  ("already accepted on 2026-06-14"). No override: there is no legitimate case
  for two admission records on one person, and the refusal is what keeps this
  form from becoming a way around the application process.
- **with no application** (a self-signup sitting at `role=external`) — promote
  that account rather than refusing. It is the same person, and someone poking
  at the site before being admitted is the common case.

### 4. The email

A new `account_ready` `MessageTemplate` key, seeded alongside the existing
admissions messages, so it appears in the coordinator's Messages tab and is
editable in place like every other admissions message. It says: your account is
ready, set your password here, then choose an advisor, read the guidelines,
build your profile, and here is My LSP.

The link is Django's own `password_reset_confirm` token — no new model and no new
expiry machinery. It is valid for **3 days** (Django's default
`PASSWORD_RESET_TIMEOUT`; the letter says 3 rather than us changing the global for
every reset on the site). If it lapses, the member uses "forgot password" like
anyone else.

The form offers three send choices:

- **full acceptance letter** — the existing `decision_accept` template, for
  someone admitted cold who has heard nothing yet;
- **account-ready invitation** — the new `account_ready` template, for someone
  already welcomed off-site (the case for the three members at hand);
- **nothing** — the account is created and the membership recorded; the Web
  Coordinator writes to the member themselves.

**Every choice writes a `WelcomeEmail` row.** Otherwise the next
`send_welcome_emails --commit` run sweeps these new active accounts and mails
them the launch "the site is live, here's how to sign in" letter — a second,
contradictory sign-in email. Choosing *nothing* suppresses it on the assumption
the coordinator is handling the member directly.

### 5. Rendering the letter without an `Application`

`admissions/emails.py` builds its applicant context from an `Application`
(`_applicant_context`). It is refactored to a `_member_context(user, *, track,
background)` with `_applicant_context(application)` as a thin wrapper over it.

`status_url` is the one context key that has no meaning for a direct admit — and
the `decision_accept` body does not use it, so nothing renders a fake link. The
guidelines-document lookup keys off the track, which the form supplies.

### 6. Out of scope

- **Dues charges** — the treasurer's Accounts → Sync charges already mints for
  active members. The success page says so rather than the form minting behind
  the treasurer's back.
- **Advisor assignment** — the member chooses an analyst and contacts them; that
  is the school's process, and `Profile.needs_advisor` already surfaces it.
- **Directory listing** — the member's own choice in the profile editor.

## Testing

- `admit_member` sets role, standing, tenure, and formation background.
- Both routes produce identical membership state for the same track/background.
- The collision guard refuses a user with an `Application`, in each status.
- An existing account with no application is promoted rather than refused.
- New accounts get an unusable password and a stamped `email_verified_at`.
- A `WelcomeEmail` row is written on all three send choices.
- The `account_ready` link sets a password end to end.
- The gate: Web Coordinator and superusers in, Applications Coordinator out.
