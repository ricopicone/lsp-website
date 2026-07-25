# Signup email verification and bot defenses

Task #471. Design date: 2026-07-25.

## Problem

Since the 2026-07-22 URL cutover made `lacanschool.org` canonical, 11 of 16 new
accounts have been bot signups. The signature is unmistakable — random
mixed-case strings in both name fields:

```
07-22 23:22  j.ejiw.eb.o1.53@gmail.com             jCJfQodHsJsObGlNNyays WLYwawJyJK
07-23 14:29  mblackey@aol.com                      xywWAzEXDdQLhEeqEaIK xMfmDcHPhGT
07-24 22:43  tjones-charles@tulaliptribes-nsn.gov  UYaQTzWmDkrxdmbzKWRj LzTDKhjmNrY
```

The first bot arrived hours after the cutover, so this is untargeted drive-by
spam against a newly-crawled domain, not an attack on the school.

`LightSignupForm` collects email, optional name, and password; `accounts.views.signup`
creates the user and logs them in immediately. There is no verification, no rate
limit, and no bot deterrent of any kind.

### Why this matters more than junk rows

Bots land as `role=external` (Auditor), which is outside `Profile.DIRECTORY_ROLES`,
so `accounts.permissions.is_lsp_member` already gates them out of Parlêtre, the
directory, and members-only areas. The rows themselves are noise, not intrusion.

The real exposure is **email reputation**. Some bot addresses are Gmail dot-abuse
variants, but others are harvested addresses belonging to real people — an AOL
account, a county government address, a tribal government `.gov`. With no
verification, anyone's address can be bound to an account. Any flow that mails
those addresses makes the school an unsolicited sender from the same SES identity
that carries dues notices, receipts, and referral mail.

## Approach

Require proof of mailbox control before an account becomes usable, and layer
invisible deterrents underneath so most bot traffic never reaches the mail step.

Considered and rejected: invisible defenses alone (cheaper, zero friction, would
have stopped all 11 — but leaves address ownership unproven), and gibberish-name
detection (brittle against real member names such as Líza Ahearne, Bou Ali, and
Patsalides Hofmann; a false positive turns away a real member).

## Design

### 1. Verification mechanism

New `accounts.EmailVerification`, mirroring the existing `EmailChangeRequest`
idiom: user FK, opaque single-use `token`, `created_at`, `confirmed_at`, and a
`next_url`. Alongside it, `Profile.email_verified_at` (nullable datetime) as the
durable record that outlives token cleanup.

- `signup` creates the user with `is_active=False`, does **not** log them in,
  sends the link, and renders a "check your inbox" page.
- `signup_verify` at `/accounts/verify/<token>/`: GET renders a confirmation page
  with a button; **POST** performs the verification.
- POST sets `email_verified_at`, flips `is_active=True`, consumes the token, logs
  the user in, and redirects to `next_url`.

**`is_active` is the right gate.** It is already the de-facto "counts as a live
user" axis — `core/staff.py:425` filters member counts on it and `core/staff.py:483`
filters directory listings — so unverified accounts drop out of those surfaces
without further work. Membership status proper lives on the orthogonal
`Profile.Standing`, so nothing is being overloaded.

**The POST gate is a deliberate deviation.** Neither `email_change_confirm` nor
`magic_link_consume` POST-gates its token today. Signup verification does, because
the `auth-email-scanner-and-reset-gotchas` memory records that link scanners consume
single-use links — and this flow specifically targets corporate, `.gov`, and AOL
addresses whose filters pre-click links.

**`next_url` lives on the row, not just the URL.** This preserves the task #464
guest funnel: someone who signs up to register for an event on a laptop and opens
the mail on a phone still lands back on that event's registration page.

TTL is **3 days**, deviating from `EmailChangeRequest`'s 24h. There is no
account-takeover vector before the account exists, and a longer window means fewer
expired-link support requests.

### 2. Bot defenses

A dedicated `accounts/antibot.py` so each check is independently testable and the
public referral form can adopt it later.

- **Honeypot** — a plausible `website` field, CSS-hidden with `tabindex="-1"` and
  `autocomplete="off"`. When filled, render the normal success page but create
  nothing, so bots get no failure signal.
- **Submit timing** — signed timestamp via `django.core.signing`; submissions under
  2 seconds produce a recoverable form error. The threshold is deliberately
  conservative, and the error is recoverable, because password managers and
  autofill can legitimately be fast.
- **IP rate limit** — Redis (already running in production), 5 signups per IP per
  hour, recoverable form error. The cap is generous because real members share
  institutional IPs.

**Ordering is load-bearing:** the honeypot and rate limit must reject *before* the
verification email is sent. Otherwise a bot signing up as a stranger's `.gov`
address still causes the school to mail that stranger — the exact reputation risk
this work closes.

### 3. Grandfathering and purge

- A data migration sets `email_verified_at = date_joined` for every existing user.
  The ~80 imported members and the 5 genuine recent signups are unaffected.
- `manage.py purge_unverified_signups` deletes users where
  `email_verified_at IS NULL AND is_active = False AND date_joined < now - 7d`.
  Because grandfathering marks every pre-existing account verified, the command
  can never reach an admin-deactivated account.

**Deployment note:** the natural home is `lsp-dues-cron`, but that timer is
deliberately disabled pending the treasurer's Owing cleanup (see the
launch-checklist memory). The purge therefore needs either its own timer or a slot
on an already-enabled daily service such as `process-referrals` (16:00 UTC). This
is host configuration, not repo state, and is called out as a follow-up.

### 4. Unverified login UX

Django's default response to an inactive user is "invalid credentials", which is
misleading and generates support mail. The login view detects an unverified
account and offers a rate-limited "we emailed you a link, resend it" path.

## Testing

- **Form** — honeypot filled creates no user *and sends no email*; sub-2s submit
  errors; over-cap submit errors.
- **Flow** — signup creates an inactive user and does not log in; GET on the verify
  URL does not consume the token (the scanner case); POST verifies, logs in, and
  honors `next_url`; expired token; reused token.
- **Purge** — removes unverified accounts older than 7 days; spares verified,
  admin-deactivated, and recent accounts.
- **Migration** — grandfathering marks all pre-existing users verified.

## Out of scope

Applying the antibot helpers to the public referral form, and the host timer
change for the purge command.
