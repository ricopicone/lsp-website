# LSP Website — Project Context

The Lacanian School of Psychoanalysis registration and payment website — a Django
application. This file orients a Claude Code session; the planning documents have
the full detail.

## What this is

Phase 1 of a custom website for the Lacanian School of Psychoanalysis (LSP),
replacing a Wix + Typeform setup. Phase 1 scope: user accounts and roles, event
registration, and payments. Target: registration live by ~mid-July 2026.

Planning documents live in the parent `LSP-Web-Coordinator` folder, alongside this repo:

- `../LSP-Website-Requirements-Spec.md` — what the site must do (requirement IDs:
  `USR-*` accounts, `REG-*` registration/payment, `PROG-*` events, etc.).
- `../LSP-Website-Architecture-Phase1.md` — the architecture and data model this
  build follows. Read it before making structural decisions.
- `../LSP-Website-Phase2-Plan.md` — Phase 2 milestone breakdown (M9–M17),
  dependency map, and the 10 open decisions that shape it. Read before
  starting any post-launch work.

## Tech stack

- Django 5.2 LTS, Python 3.10+ (`.python-version` pins 3.10; `requires-python` is
  `>=3.10`, so raising it is free).
- uv for dependencies and the virtual environment.
- SQLite for local development; PostgreSQL in production (via `DATABASE_URL`).
- Stripe (hosted Checkout) for payments and Amazon SES for email — both built and
  live (SES production access granted 2026-06-03; out of the sandbox).
- Realtime chat (Parlêtre) over Django Channels + daphne (ASGI); in-memory channel
  layer in prod, Redis gated behind `PARLETRE_USE_REDIS`.
- Hosting: AWS, live on the `app.lacanschool.org` subdomain.

## Commands

```
uv sync                                  # install dependencies
uv run python manage.py migrate          # apply migrations (local SQLite)
uv run python manage.py createsuperuser  # create an admin (prompts for email)
uv run python manage.py runserver        # dev server at http://localhost:8000/
uv run pytest                            # run the test suite
uv run ruff check .                      # lint
npm install                              # one-time: install Tailwind + DaisyUI + esbuild
npm run watch:css                        # dev: rebuild static/css/site.css on save
npm run build:css                        # one-shot minified build
npm run build:js                         # bundle the vendored TipTap doc editor
```

The CSS pipeline (Tailwind v4 + DaisyUI v5) compiles `static/css/input.css`
to `static/css/site.css`. The output is `.gitignore`'d — rebuild before
running the dev server, or run `npm run watch:css` in a second terminal.
The Work-tab document editor's TipTap bundle is **vendored** (no runtime
CDN): `assets/js/doc-editor.src.js` is bundled by esbuild to
`static/js/vendor/doc-editor.js`, which **is** committed. After editing the
source, run `npm run build:js` and commit the rebuilt bundle. The Daily.co
video client is vendored the same way (`assets/js/daily.src.js` →
`static/js/vendor/daily.js`); `npm run build:js` rebuilds both.
`base.html` links `{% static 'css/site.css' %}` and sets `data-theme="silk"`
(light) with `abyss` (dark) auto-applied via `prefers-color-scheme` and a
manual toggle. **Authoring rule: use DaisyUI semantic tokens
(`bg-base-100`, `text-base-content`, `text-primary`, …) — never hardcoded
colors like `bg-gray-100`** — so theme switching works without per-component
fiddling.

## Layout and conventions

```
config/         project — settings/, urls.py, wsgi.py, asgi.py
  settings/     base.py + development.py (default) + production.py
accounts/       custom User, Profile, directory, profile editor, import   <- built
committees/     Committee (USR-7); roster on its attached Workgroup        <- M2 / folded-in
events/         Events, Sessions, PriceTier, PricingCode, recurrence helper <- M2
registrations/  registrations                                              <- M3
payments/       payments, receipts, Stripe, dues + tuition lifecycle       <- M4/M6/M7.5
core/           shared utilities, unified calendar (PROG-6)                <- M2/M3
content/        editable site pages (about, etc.)                          <- Phase 2
works/          faculty/member publication showcase                        <- Phase 2
documents/      newsletters / shared documents                            <- Phase 2
parletre/       Parlêtre members-only discussion board (MEM-3, M13.5)      <- Phase 2
workgroups/     shared Workgroup layer (roster+channel+works+files)        <- Phase 2
cartels/        Cartels (CART-1/2/3), built on the Workgroup layer         <- Phase 2
workinggroups/  Working groups, built on the Workgroup layer               <- Phase 2
video/          Daily.co in-site meeting rooms (one per Workgroup)          <- Phase 2
```

- Settings are split by environment. `DJANGO_SETTINGS_MODULE` defaults to
  `config.settings.development`; production uses `config.settings.production`.
- Configuration comes from environment variables (django-environ); see
  `.env.example`. No secrets in the repo.
- `accounts.User` is a **custom user model** (email login, no username) and is
  already wired as `AUTH_USER_MODEL`. Extend it; never swap it.
- Every `User` gets a `Profile` automatically via a post-save signal.
  `Profile.role` (seven LSP roles) is the single source of truth for pricing
  tiers and members-only access. `Profile.is_faculty` is an orthogonal axis;
  the faculty-only fields (`bio`, `headshot`, `default_billing_mode`, `public`)
  live on Profile itself rather than a separate model — every user has a
  Profile anyway, and some of those fields may turn out useful for members
  generally in Phase 2.
- **Workgroups layer (Phase 2):** cartels, working groups, committees, and
  seminars all share one `workgroups.Workgroup` (roster via
  `WorkgroupMembership`, an auto-provisioned Parlêtre channel, shared works/
  files, capability toggles seeded per kind). Concrete types *attach* a
  Workgroup: `Cartel`/`WorkingGroup` are thin attach-models, `Committee` keeps
  its charter/public page + attaches one (roster relocated off the removed
  `CommitteeMembership`), and `Event` (seminar) attaches one whose roster is
  *derived* from faculty + paid/comped registrants. **When adding a group
  feature, put it on `Workgroup` first.** See `docs/design-workgroups.md` +
  the `workgroups-architecture` memory.
- Committees (Board, Programming Committee) drive admin permissions; **LSP
  Staff is now the `Profile.is_lsp_staff` designation**, not a committee — it
  grants board entry, event-edit, and an `access=lsp_staff` Parlêtre channel.
- **Django messages render once**, from `core/templates/core/_messages.html`,
  included by `core/base.html`. Never add a per-page messages loop: a second
  rendering prints every message twice. `core/test_templates.py` enforces this.
- Tests use pytest-django; lint with ruff. Keep both green — CI runs them on push.

## Design principle: do not over-automate

The school explicitly asked that automation not remove human discretion. Faculty
use sliding-scale and "none turned away for lack of funds" pricing; tuition-paying
members are exempt from seminar fees; some faculty bill per class. Every automated
path must keep a manual staff override. See architecture document sections 4.1
and 6.4.

## Status

Done (see `git log` for specifics):

- Project scaffold — Django project, five apps, split settings, GitHub Actions CI,
  smoke test.
- User / Profile / roles — email-login `User`, `Profile` with the seven LSP roles,
  auto-created per user, plus the admin back office. (Per-year tuition status
  later moved off Profile into `payments.TuitionEnrollment` — see M7.5 below.)
- CSV bulk-import (`USR-3`) — `manage.py import_users path/to/file.csv`
  with `--update` and `--dry-run`. Atomic, dedupes by email case-insensitively,
  creates users with an unusable password (they set one via password reset
  once SES is wired up).
- AWS skeleton deployment — Phase 1 skeleton live at
  `https://app.lacanschool.org/admin/` on a single t4g.small EC2 (Amazon
  Linux 2023, `~/lsp-website/`) running the Django app in Docker via
  `compose.yml`, fronted by host-level nginx with a Let's Encrypt cert
  (auto-renewed via a systemd timer). Postgres 16 on RDS `lsp-db`
  (db.t4g.micro, private). Email on SES (DKIM-verified; **still in sandbox —
  production-access case 178015607900328 awaiting AWS re-review, not a final
  denial; monitor `ProductionAccessEnabled`**; see `ses-status` memory). See `aws-infra` memory for endpoints, SG IDs, and the
  Secrets Manager ARN for the RDS master password.
- Milestone 1 complete (USR-1 through USR-5).
- Profile extension (USR-6) — `is_faculty` orthogonal axis plus `bio`,
  `headshot`, `default_billing_mode`, `public`. Bulk importer accepts
  `is_faculty`.
- `committees` app (USR-7) — `Committee` + `CommitteeMembership` with
  structured term dates and named roles. Seeded with Board, Programming
  Committee, LSP Staff.
- `events` data model — `Event`, `Session`, `PriceTier`, `PricingCode`
  (REG-17). Django admin for all.
- Recurrence helper + `manage.py generate_sessions` (PROG-5) — weekly,
  monthly-ordinal, or explicit-dates patterns via `dateutil.rrule`.
- Unified month-grid calendar at `/calendar/` (PROG-6) — FullCalendar.js,
  staff-gated, JSON feed at `/calendar/events.json`.
- Milestone 2 complete.
- Public event page at `/events/<slug>/` (PROG-1); drafts hidden from
  anonymous users but previewable by staff and event editors.
- Auth (architecture § 6.1) — Django `LoginView` + `LogoutView` + custom
  `signup` view at `/accounts/{login,signup,logout}/`. Login / signup /
  logged-out templates under `accounts/templates/registration/`.
- Pricing resolver (`events.pricing.resolve_price`, architecture § 6.2) —
  one well-tested function: tier base, covered-by-tuition short-circuit,
  sliding scale, all three pricing-code modes.
- `registrations` app — `Registration` model + admin; registration form,
  view, and templates at `/events/<slug>/register/` + confirmation page.
  Atomic, decrements `PricingCode.uses_remaining`; `$0` short-circuits
  to `PAID` (no Stripe roundtrip).
- Faculty edit form (PROG-7) at `/events/<slug>/edit/` — gated by
  `events.permissions.can_edit_event` (event faculty, Programming
  Committee, LSP Staff, or Django `is_staff`).
- Faculty roster + pricing-code generation (PROG-8) — `?view=faculty`
  on the event page renders the roster and a mint-code form;
  `/events/<slug>/codes/` POST creates a `PricingCode`.
- Milestone 3 complete.
- Self-service registration cancel (REG-16, pulled forward from M6) —
  cancel button on the confirmation page; Stripe refund automated via
  `stripe.Refund.create`; webhook `charge.refunded` handler; pricing-code
  uses restored on cancel.
- Public landing page at `/`, public events list at `/events/`, calendar
  is now public (drafts visible only to staff).
- Dues at `/dues/` (login req; amount is role-tiered on `DuesPeriod`
  — pre-candidate $50 / candidate $100 / analyst·scholar $150),
  donations at `/donate/` (anon OK; `Payment.email` carries the
  receipt address). Receipt template now type-aware.
- Generic post-payment thanks page at `/payments/<id>/thanks/` for
  non-registration payments.
- Roster CSV at `/events/<slug>/roster.csv` (REG-10, can_edit_event gated).
- Transactions CSV at `/payments/transactions.csv` (REG-15, staff gated;
  filters: type, since, until). Linked from landing for staff.
- Milestone 5 complete.
- Dues lifecycle — `DuesPeriod` (academic year), `Payment.dues_period`,
  auto-rollover + weekly reminders via systemd timer
  (`lsp-dues-cron.timer`), landing-page banner for obligated unpaid
  members, treasurer dashboard at `/treasurer/` with Chart.js
  (per-period totals, per-role breakdown, unpaid list).
- Manual-override admin actions (REG-14) — *Comp selected registrations*
  on Registration admin, *Apply payment success* on Payment admin
  (drives the same complete_payment() helper the Stripe webhook uses).
- Confirmation email + event page now grant access_info for both PAID
  and COMPED statuses.
- Security review: `manage.py check --deploy` clean against
  `config.settings.production`; production.py has the full HTTPS / HSTS
  / cookie-secure / proxy-SSL-header / CSP-adjacent set.
- Milestone 6 substantially complete (REG-14 + REG-16 + security pass;
  broader fuzz/coverage sweep is the remaining piece).
- `payments` app — `Payment` (with `stripe_checkout_session_id`
  unique-when-set as the webhook idempotency key) and `Receipt`
  (sequential `LSP-YYYY-NNNN`). Django admin.
- Stripe Checkout integration — `payments.stripe_checkout` creates the
  Session with the resolved amount; the register view redirects to it
  for nonzero registrations; `$0` short-circuits straight to PAID.
- Stripe webhook at `/payments/webhooks/stripe/` — signature-verified,
  idempotent, marks Payment SUCCEEDED + Registration PAID + creates
  Receipt + sends emails. Email failures don't rollback the DB or
  trigger Stripe retries.
- Transactional emails (REG-7/8/9) via `EmailMessage` with `Reply-To:
  SUPPORT_EMAIL` (`website@lacanschool.org` by default). Access info
  released on the event page and in the confirmation email only when
  the user has a paid Registration.
- Register form polish — clean tier labels, role pre-selection, hidden
  sliding amount until needed, one-click "covered by tuition" panel for
  matching tuition-paying members.
- Sliding-floor pricing codes (REG-17) now set a minimum (matching the
  mode name): require sliding_amount input ≥ floor.
- Production LOGGING in base settings: 5xx tracebacks land in container
  logs even with DEBUG=False; webhook handler explicitly logs exceptions.
- Milestone 4 complete.
- Member roster bulk-loaded — 80 members from the public Wix directory
  (Analysts of the School, Candidate Analysts, Pre-Candidate Analysts,
  Candidate Scholars, Pre-Candidate Scholars) imported to prod with full
  bios, credentials, languages, location, normalized phones (E.164 via
  `django-phonenumber-field`), and headshots downloaded from the Wix CDN
  into S3. Profile gained `credentials`, `languages_spoken`, `location`,
  `phone`, `public_email` (login email vs. publicly-listed email — some
  members use different addresses for each). `Role` extended with a
  scholar track (`scholar`, `candidate_scholar`, `pre_candidate_scholar`).
- Public directory at `/directory/` — grid grouped by role, client-side
  search, per-member detail pages. Serif headings, neutral palette,
  responsive card grid. Style is template-local for now (no shared
  stylesheet); easy to factor when visual identity gets formalized.
- Self-service profile editor at `/accounts/profile/` (replaces the old
  "Edit profile · soon" stub). Members edit name, photo, bio, contact,
  public listing, and practice details; `role`/`is_faculty` stay
  staff-only (read-only). Headshots go through a Cropper.js modal
  (circular overlay + bust guide + zoom) and a Pillow pipeline that
  normalises every upload to a **512² WebP square** (kept non-destructive
  via `headshot_original` + `headshot_crop`), so all the circle/square
  frames across the site render correctly with no per-site changes. New
  Profile fields harvested/enriched: `year_joined` (AY joined),
  `display_name`, `pronouns`, `website`, `specialties`,
  `consultation_modalities`. Editing `location` stales the geocode so
  `geocode_profiles` re-resolves map pins. The timezone picker is folded
  in (`/accounts/timezone/` now redirects there). See `profile-editor` memory.
- Self-service **login-email change** at `/accounts/email/change/` —
  verify-before-switch: password re-auth + uniqueness check → emails a
  single-use 24h link to the new address → confirm switches `User.email`
  and notifies the old address. Gated until launch by
  `DJANGO_EMAIL_CHANGE_ALLOWLIST` (default: rico's address) unless
  `DJANGO_EMAIL_CHANGE_PUBLIC=true`. `EmailChangeRequest` is admin-auditable.
  See `email-change` memory.
- **M7.5 — per-year tuition lifecycle** (replaces the old single
  `Profile.tuition_paying` boolean, now dropped). `payments.TuitionPeriod`
  (academic-year cycle, mirrors `DuesPeriod`) + `TuitionEnrollment`
  (per-year decision: `COMMITTED` / `PAYMENT_PLAN` / `PAID_IN_FULL` /
  `SKIPPING`; absence of a row = no decision) + `TuitionInstallment`
  (payment-plan scaffold). REG-4 "covered by tuition" now keys off
  `Profile.is_tuition_current()` for the *current* academic year, not a
  global flag. Reminders from Sept 1 reuse the dues cron
  (`send_tuition_reminders`). Treasurer guide at `/treasurer/help/`
  (`core/docs/treasurer-guide.md`) is the canonical policy doc.
  See `tuition-lifecycle` memory.
- **Email-based auth — password reset + magic-link + admin 2FA** (shipped
  once SES left the sandbox). Django's built-in password-reset flow wired
  under `/accounts/password/reset/` (templates under `accounts/`, not
  `registration/`, since `django.contrib.admin` shadows the latter);
  passwordless **magic-link** sign-in (`MagicLoginLink`, 15-min single-use,
  offered alongside the password form, no user enumeration); and **admin
  TOTP 2FA** (`pyotp` + `qrcode`, `TOTPDevice` + hashed `RecoveryCode`s,
  helpers in `accounts/twofactor.py`). 2FA *eligibility* is
  `core.staff.can_access_admin_tools`; **enforcement is gated OFF** behind
  `DJANGO_TWO_FACTOR_ENFORCED` (default false) so current testers aren't
  blocked — enrollment at `/accounts/2fa/setup/` works regardless. See
  `email-auth-2fa` memory.
- **Event page structured content** (task #245, Reinhardt feedback, shipped
  2026-06-11). `Event` gained `readings` (one citation per line),
  `schedule_note`, `contact`, `fee_note`, rendered as real sections
  (Readings = hanging-indent citation list); the faculty edit form exposes
  them and proposal approval now mints `ProposalReading`s + contact onto the
  Event. Member-text italics via `*asterisks*`
  (`events.event_format.inline_italics` — escape-then-`<em>`; the proposal
  citation style guide teaches it). Sessions section renamed **Schedule**;
  >4 sessions collapse behind "All N sessions" with a next-3-upcoming
  preview. 2026-27 program re-imported with split fields —
  **`import_program_2026_2027` re-runs clobber admin-side edits; diff prod
  against the script first** (see `event-structured-content` memory).
- **Web-developer API + MCP server** (task #252, shipped 2026-06-12). A
  token-authenticated JSON surface (`devapi` app, mounted at `/devapi/`) plus a
  thin stdio MCP server (`mcp/lsp_mcp_server.py`) that lets a Claude Code
  session manage the site directly — closing the suggestion-box loop (no more
  `export_suggestions` → read markdown files). `DevApiToken` stores only a
  SHA-256 hash of a `lspdev_…` token **bound to a real user**; every request is
  authorized through that user's existing `core.StaffRole` checks
  (`@dev_api` decorator), so the API can never do more than the holder could in
  the web UI. Endpoints/tools (Suggestions slice): `whoami`,
  `list_suggestions`, `get_suggestion` (incl. server-resolved view + URL name),
  `update_suggestion` (same triage side-effects as the human view —
  reviewed_by/at + submitter notification), `suggestion_stats`. Mint a token
  with `manage.py create_devapi_token --user … --label …` (printed once). The
  `mcp`+`httpx` deps live in a separate `mcp` dependency group (laptop-only —
  out of Docker/CI); the server reads `LSP_DEVAPI_TOKEN` from the env, falling
  back to `~/.config/lsp-mcp/.env` across worktrees. This is distinct from
  Codex's remote `projects-direct` MCP config: `bearer_token_env_var` must name
  an exported variable, not contain the token value itself; if a static
  `Authorization = "Bearer …"` header is present, omit `bearer_token_env_var`.
  Kill switch `DJANGO_DEVAPI_ENABLED=false`. Built to grow into a broader admin
  surface (health/deploy, member lookups, treasurer/referral read models). See
  `mcp/README.md` + the `devapi-mcp-server` memory.
- **Faculty editing review loop** (task #295). Editing the *content* fields
  (title, description, readings, fee note) of an **approved** event — published
  *and* minted from an approved PC proposal, of a proposable type
  (seminar/reading group/special event) — now routes through a
  certify-or-submit dialog (`events/<slug>/edit/` → `event_edit_confirm.html`).
  Non-reviewable fields (schedule_note, contact, record_video) still apply
  immediately, and events not from a proposal edit freely as before
  (`Event.requires_change_review()`). Faculty get two options — *minor* (adopted
  now) or *substantial* (held in the PC queue); PC/staff reviewers
  (`events.permissions.is_change_reviewer`) get a third *administrative change*
  option that applies immediately with an audit record. The ~20%
  description-change heuristic (`events/review.py:change_ratio`) is **advisory
  only** — it recommends the review path but never forces it (do-not-over-
  automate). Every dialogged change leaves an `events.EventChangeRequest` audit
  row (status SELF_CERTIFIED / ADMINISTRATIVE / PENDING / APPROVED / DECLINED);
  the live event is untouched while a change is PENDING. PC review queue at the
  new **Changes** tab of the program admin (`program_admin_changes` +
  `change_request_decide`); notifications via the new
  `EVENT_CHANGE_REVIEW` category (PC on submit, proposer on decision). `title`
  is now editable on the faculty edit form.
- **Shared school officers — President / Vice President** (task #428). The
  Board's Chair / Co-chair are the school's President / Vice President — a
  display relabel (`workgroups.OFFICER_TITLES` / `role_label`, tasks #368/#428)
  *and* now a synced governance record. The Board's Chair/Co-chair
  `WorkgroupMembership`s are the **single source of truth**:
  `committees.officers.sync_school_officers()` recomputes the President /
  Vice-President `StaffRole` holders from the Board's serving roster, fired by a
  `post_save`/`post_delete` signal on `WorkgroupMembership` **and** a new
  `workgroups.roster_changed` signal (for the bulk-`.update()` `remove_member` /
  `leave` paths that bypass model signals). The **Meeting of Analysts** roster
  derives its President / Vice President leader chips from those synced roles
  (`Workgroup.participants()`; `Participant.officer_title` override). Board →
  Appointments no longer manages the two officer roles (set them in the Board's
  Settings roster). One-time reconcile migration
  (`committees.0010_reconcile_school_officers`). See the `board-officer-titles`
  memory + `docs/superpowers/specs/2026-07-12-shared-school-officers-design.md`.
- **Tuition clearance gate + treasurer payment re-categorize** (task #439).
  Promotion to Analyst/Scholar is blocked while tuition is unsettled (any
  uncovered tuition charge, or fewer than four covered years) —
  `payments.ledger.tuition_clearance()` enforced at the membership
  chokepoint (`accounts.membership.validate_role_transition`), the Meeting
  of Analysts' advancement approval, the Board membership form, the Django
  admin role field, and the CSV importer (skips + warns); no override
  switch — settling the member's ledger *is* the override. The treasurer's
  Payments tab and member statement gained **Re-categorize**, an audited
  action that re-types a payment (with a bound dues/tuition period) and
  allows donation flips; retyping away from tuition unwinds an unbacked
  installment and leaves a review note rather than auto-changing the
  enrollment decision.
- **Member Account v2** (task #439). The member's Tuition + "My account"
  tabs are now one **Account tab**, with a "Requirement met" (payment-based,
  `tuition_years_covered` ≥ 4) vs. the enrollment-based **decision
  exemption** (`tuition_decision_exempt`, ≥4 non-skipping years — only
  silences the annual-decision nag, doesn't imply paid) kept as two
  explicitly distinct predicates. Members get full statement-action parity
  with the treasurer on their **own** payments — re-categorize, split
  (donation flips included), and note — via `my_payment_retype`/
  `my_payment_split`/`my_payment_note`, all stamped `source=SELF_REPORTED`
  ("Member-reported") and audit-noted by email so the treasurer's
  provenance hover always shows who acted. The retired My-payments table is
  gone. A new **history-submission queue** (`payments.LedgerSubmission`)
  lets a member report a pre-website payment or fee; the treasurer's
  Reconcile tab reviews each (approve mints a member-reported Payment/Charge
  bound to the right AY period with a duplicate-charge guard; decline just
  notes it), and the member is notified either way.
- **Registration Admin console** (task #470) at `/admin-tools/registrations/`
  (`registrations/views_admin.py`, referrals-console tab pattern). Cross-event
  registration table (filters/search/CSV, "Needs attention" pending strip) with
  approve / decline / comp / add-note row actions, an Events tab with
  per-status counts and an open↔close registration toggle (open flips
  DRAFT/CLOSED→OPEN, matching the PC bulk view; publishing stays separate),
  and a Help tab (`core/docs/registrar-guide.md`). Gated by
  `registrations.permissions.can_administer_registrations`: the new **unheld
  `registrar` StaffRole** (a placeholder for a future position — excluded from
  directory badges like LSP Staff), Web Coordinator, serving Programming
  Committee (live roster check), or Django staff/superusers. The admin comp
  action's side-effect chain moved to
  `registrations/services.py::comp_registration` so console + admin share it.
- **Signup email verification + bot defenses** (task #471). After the URL
  cutover made `lacanschool.org` canonical, 11 of 16 new accounts were
  drive-by bots. The exposure wasn't the junk rows (new accounts are
  `role=external`, already gated by `is_lsp_member`) but **email reputation** —
  some bots registered real people's harvested addresses, and with no
  verification any address could be bound to an account, putting the SES
  identity that carries dues, receipts, and referrals behind unsolicited mail.
  Signup now creates the user `is_active=False` and does **not** log them in;
  `accounts.EmailVerification` (mirrors `EmailChangeRequest`, 3-day TTL)
  carries `next_url` **on the row** so the task #464 guest event funnel
  survives opening the link on another device. **The verify view is
  POST-gated** — GET only renders a confirm button — because mail scanners on
  exactly these corporate/`.gov` addresses pre-click links; note neither
  `email_change_confirm` nor `magic_link_consume` does this.
  `Profile.email_verified_at` is the durable record, grandfathered onto every
  pre-existing account by `accounts/0042`, so a null now means "self-signup
  that never confirmed" and nothing else — which is what lets
  `manage.py purge_unverified_signups` (host timer `lsp-signups-purge`, daily
  18:00 UTC) delete stale bot rows without ever reaching a deactivated member.
  `accounts/antibot.py` adds a honeypot, a 2s minimum fill time, and a per-IP
  cap; **the honeypot and rate limit reject before the mail sends**, or a bot
  using a stranger's address still makes us mail that stranger. Its `.hp-wrap`
  rule is plain CSS in `assets/css/input.css`, not a Tailwind utility (the
  class is set in Python — see the tailwind-classes-set-in-python gotcha). The
  login page distinguishes an unconfirmed account from bad credentials and
  offers a resend. Fixed en route: `Profile.save()`'s `deceased_on` →
  `is_active` sync treated Profile *creation* as a transition, so the
  auto-create signal re-enabled **any** user created inactive.
- **Category-scoped coverage + dues bucket** (task #473). **The single
  account ledger is the ground truth and is unchanged** — one obligation,
  one paid total, one net balance, one running statement, across every
  category, exactly as #439 specified. What changed is the *meta accounting*
  read off it. The #439 sweep swept one pot of *all* non-donation payments
  across *all* OPEN charges oldest-first, category ignored, so registration
  and dues money got retro-credited to older tuition years. Symptom: an
  account showing three tuition years paid plus "$1,870 / $2,000" on a
  fourth against $6,000 of tuition payments (the $1,870 was exactly that
  member's non-tuition money minus the one dues charge sorting ahead of the
  last tuition year), while four registration fees paid in full on the day
  read as **unpaid**. Not merely cosmetic: `tuition_years_covered` gates
  promotion (`ledger.tuition_clearance`, the "Requirement met" badge,
  `tuition_decision_exempt`). `_charge_states` now covers each category's
  charges oldest-first **from that category's payments only — no
  cross-category coverage at all, not even for a surplus**. A miscategorized
  payment surfaces as an unpaid charge in the short category, which is the
  point: the fix is to re-categorize it, not to let the wrong bucket read as
  paid. (An intermediate category-scoped-*then*-spill design was built and
  rejected — spillover is fungibility.) **Dues gains the bucket treatment
  tuition had**: `dues_obligation` / `total_dues_paid` / `dues_balance` /
  `dues_owed` / `dues_credit` / `dues_rows` on `member_account`, the same
  figures on `accounts_overview`, a "Dues, all years" tile + "Dues by year"
  table on the treasurer member page, a Dues (all yrs) column on Accounts,
  two new balances-CSV columns, and an all-years dues summary on the
  member's own Account tab. Balances cannot move (they're computed
  independently of coverage) — verified on prod across all 81 members with
  ledger activity: 0 balance mismatches, 18 members re-attributed, 6
  tuition-year counts (all upward, none crossing the 4-year gate).
  Read-time only: no migration, no backfill. Amends decision 1 of the #439
  spec; see
  `docs/superpowers/specs/2026-07-25-category-scoped-coverage-sweep-design.md`.
  **Note for the treasurer's Owing pass:** members whose dues charge was
  being silently covered by tuition money now correctly read as owing dues
  (and vice versa) — same dollars, real shortfalls no longer hidden.
  `send_dues_reminders` keys off `dues_state`, so those members will be
  reminded once `lsp-dues-cron.timer` is enabled.
- **Abandoned checkouts + treasurer clarity** (task #474). A `Payment` row
  is minted the moment a member is *sent* to Stripe Checkout, so PENDING
  has only ever meant "we asked" — and nothing told the site when a session
  expired unpaid (~24h TTL), so stale PENDING rows accumulated (one per
  attempt: `pay_registration` mints a fresh row on every retry) reading to
  the treasurer as "this might have gone through". Two prod rows were
  exactly that, confirmed against Stripe (`status=expired`,
  `payment_status=unpaid`, no `payment_intent`).
  **`Payment.Status.ABANDONED`** is the new terminal state — deliberately
  distinct from FAILED, since a declined card is an attempt to pay and a
  closed tab isn't; the ledger already counts only SUCCEEDED, so neither
  moves money. Settled by two paths sharing `payments/stripe_sync.py`: the
  new **`checkout.session.expired`** webhook branch (seconds; **the Stripe
  endpoint's `enabled_events` must list it** — it was
  completed+refunded only), and **`manage.py reconcile_stripe_pending`**
  (nightly host timer), which re-asks Stripe about every PENDING stripe row
  older than 25h. The sweep is the part that earns its keep: a session
  Stripe reports as *paid* runs the normal `complete_payment` chain, so a
  **missed completion webhook can no longer silently cost the school a
  registration**. Abandoning never touches the Registration — it stays
  AWAITING_PAYMENT so the member can still pay and reminders keep nudging.
  Also: `Payment.add_note` (mirrors `Charge.add_note`), an "Abandoned"
  ghost badge + status filter, the **Dues (this AY)** column dropped from
  the Accounts roster (display only — `dues_state` still drives reminders
  and the double-payment guard), and treasurer-guide sections spelling out
  that **Sync charges mints obligations and never fetches payments** (the
  question that started the task) and what Pending vs Abandoned means.
- **Stripe-importer duplicate matching** (task #474, found while auditing the
  above). Two defects in `payments/stripe_import.py`, fixed in sequence.
  (1) A **dues type inferred from the amount alone** then used "member
  already has dues this AY" as duplicate proof — the guess proving itself,
  which silently dropped four real off-site Typeform charges ($350; all four
  payers had already paid dues that year, so the second payment was almost
  certainly a seminar fee). Now an amount-only guess contradicted that way is
  *dropped* and the charge surfaces as unknown; metadata/description-typed
  dues still use the once-per-year rule. (2) That fix over-fired, because the
  **amount+date overlap check required `method=offline`** — the treasurer's
  spreadsheet recorded the whole 2024 dues season as `method=stripe,
  source=imported` rows with **no payment_intent**, identical date and
  amount, so ~60 genuine duplicates suddenly read as unrecorded. Overlap
  candidates are now succeeded IMPORTED/VERIFIED rows carrying **no
  payment_intent** (an id match is impossible for those; method is
  irrelevant), which also killed a **latent $800 tuition double-count** that
  a full-history `--commit` would have created. **`--verbose-rows` was a dead
  flag** — declared, never read — which is exactly how a wrong "likely ledger
  duplicate" verdict stayed invisible; it now prints every charge's action
  and reason. (3) A third defect the first two exposed: the matcher pool was
  `User.objects.filter(is_active=True)`, and **`Profile.deceased_on`
  deactivates a deceased member** — so their payments matched no one, and
  with no `user_id` the duplicate check can't run *at all*. Barbara Freeman's
  $100 (2024-10-14) and $100 (2025-09-22), both already on her ledger, were
  offered as $200 of new money; committing would have doubled them on a
  deceased member's account. The pool now excludes only never-verified
  signups (`is_active=False` + no `email_verified_at` — what
  `purge_unverified_signups` treats as a bot row), with `deceased_on`
  re-admitting regardless.
  **End state (verified on prod 2026-07-26):** full history = 858 charges,
  611 already imported, 190 ledger duplicates, 48 unpaid, **$0.00 of new
  money**, and 9 leftover unknowns that are all $1–$20 card tests. Eight
  charges were imported provisionally along the way (source=ASSUMED, **on the
  Reconcile tab awaiting real categories**): Dopchiz $150, Cicolli $50,
  McCann $100, Rivera Rodriguez $50, Wittenberg $50, Barnwell $50,
  Barensfeld $50, Meyer $100 — $600. **No tuition-year count moved**, so the
  promotion gate is untouched, and no `audit_ledger` disagreement is
  attributable to them (the dues ones are the pre-existing #473
  category-scoped shortfalls awaiting the treasurer's Owing pass). Worth a
  look: Rivera Rodriguez's dues shortfall is exactly $50 and her provisional
  row is a $50 typed as tuition — plausibly the same money, one re-type away.
- **Direct admission** (task #476). A member admitted outside the site had no
  path in: `Application` is a `OneToOne` on a `User` requiring a letter of
  intent, so the coordinator couldn't retro-create one, and admitting by hand
  meant four surfaces (Django admin for the account, Board membership admin for
  role/standing, the MoA backgrounds page, the profile editor) with **no letter
  at the end**. Now one form at `/admin-tools/web-coordinator/admit/`
  (`admissions/direct_admit.py`, `StaffRole.WEB_COORDINATOR`-gated) creates the
  account and admits them. The admission itself is **not** reimplemented:
  `admissions.services.admit_member()` is the shared chokepoint (membership
  change + formation background) that `accept_application()` was refactored
  onto, so the two routes can't drift; the tenure note records which one was
  used. The form is in the **Web Coordinator's** admin on purpose, not the
  Applications Coordinator's console: a second admission button inside the
  application process invites reaching for the shortcut. The structural half of
  that is the form's guard, which refuses any email with an `Application` row in
  **any** status, with no override, and links to that application instead; an
  account with no application (a self-signup at `role=external`) is promoted in
  place. New accounts get an unusable password (password reset is the way in,
  and `ReplyToPasswordResetForm` deliberately reaches unusable-password rows)
  plus a stamped `email_verified_at`, since a null there means "self-signup that
  never confirmed" and would make a staff-vouched account look like a bot row to
  `purge_unverified_signups`. Send is a choice of the full `decision_accept`
  letter (rendered without an application via the new `_member_context`), a new
  **account-ready invitation** for someone already welcomed off-site
  (`accounts.emails.send_account_ready`, a 3-day `password_reset_confirm` link
  with the magic-link fallback), or nothing — and **all three write a
  `WelcomeEmail` row**, or the next `send_welcome_emails` run would mail the new
  member a second, contradictory sign-in letter. The effective-AY choices run one
  year past the current AY (`academic_year_choices` stops at the current one, but
  a member admitted over the summer is joining for the year about to start).
  Dues charges stay with the treasurer's Sync charges; the success message says
  so.

- **Referral spam screening** (task #479). Referral request `26-0727` was a
  commodity form-spam bot: every visible text input filled with a random
  mixed-case token, every checkbox checked, and a harvested real address in
  the email field. It got through because `ReferralRequestForm`'s honeypot was
  a `forms.HiddenInput` — `type="hidden"`, the one variant commodity bots skip
  on purpose — while the signup form's (task #471, `accounts/antibot.py`) is a
  CSS-hidden **text** input, which this bot demonstrably would have filled.
  Prod runs `ack=auto dist=auto`, so the school auto-acknowledged a stranger
  and distributed gibberish to the entire referral list; one clinician
  responded to it. Now two layers. **Transport** (`accounts/antibot.py`, newly
  adopted here with a per-form `looks_too_fast(minimum=…)` — 10s for this
  two-step wizard vs. signup's 2s) drops near-certain bots to the ordinary
  thank-you page, recording a deliberately **content-free** `BlockedSubmission`
  row (timestamp + reason, no address, no IP, nothing to leak) so the hit rate
  is visible — without it, a screen that silently broke and started eating real
  requests would look identical to one that works. **Content**
  (`referrals/screening.py`, a pure function) puts anything suspicious into the
  new `Status.HELD`: not acknowledged, not distributed, bell to the coordinator
  only, with `services.SuppressedStatusError` guarding `send_acknowledgment`
  and `distribute` so no future caller can leak one. The heuristics are
  gibberish detection (≥8 chars, `isalpha()`, ≥4 upper/lower transitions), a
  40-character narrative floor, and URL markers. **Vowel ratio was specified,
  then rejected during implementation**: at any threshold catching the junk it
  also flags `Pittsburgh` (0.20 — an actually-submitted location), `Frankfurt`,
  and `they/them`; case transitions separate the populations cleanly (junk
  scores 5–15, every real value scores 1). The screen only ever *holds* —
  `JUNK` is set by a human, via a Mark-as-junk button available on any request
  for the coherent-but-fake submission no heuristic will catch.
  `process_referrals` escalates a hold left unreviewed past
  `held_escalation_days` (default 3) to one email, bounding what a false
  positive costs someone in distress. Two pre-existing test payloads had
  sub-40-character narratives and were lengthened to stay realistic rather
  than weakening the floor. Design:
  `docs/superpowers/specs/2026-07-27-referral-spam-screening-design.md`.

- **Applications Coordinator directory badge** (task #481). Every other named
  coordinator badges the Directory; this one didn't, because two decisions
  intersected. The role was deliberately retired as a `core.StaffRole`
  (`core/migrations/0011`, task #272) in favour of an officer role on the Meeting
  of Analysts workgroup, and `_directory_qs()` filters its committee-badge
  prefetch to `committee__public=True` while the Meeting of Analysts is seeded
  `public=False` — so the holder fell through *both* paths. **`Committee.public`
  gates only three things** (the workgroup's `landing_visibility`, directory
  badging, and a Public/**Internal** chip in the Board's committees admin) and
  asserts nothing about confidentiality; "Internal" is the app's own word for it,
  and for the Meeting of Analysts it is mostly just the unchanged default —
  `seed_committees.py:98-100` force-opts-in every committee it carries a roster
  for, and the Meeting isn't one of them. It should nonetheless stay Internal:
  `committees/0009` sets `auto_member_role="analyst"`, so **membership is derived,
  not appointed** — flipping the committee public would stamp "Meeting of
  Analysts" onto every analyst beside the "Analyst" role badge that already says
  it. Hence the organising rule, which is what the code encodes: **badge appointed
  positions, never derived membership.** A new prefetch collects serving officer
  memberships on `kind=COMMITTEE` workgroups whose committee is *not* public,
  `.exclude(role=MEMBER)` — that exclusion is load-bearing, not tidying — and
  `_badge_officer_roles` renders them as standalone **secondary** badges showing
  `role_label` only, never naming the Internal committee. Positions already shown
  by a StaffRole badge or a public committee officer badge are dropped so one
  appointment never yields two chips (`StaffRole.name` is admin-editable, so it's
  the better label where both exist). Restoring the StaffRole and syncing it from
  the roster (the President/VP precedent) was rejected: `StaffRole.holders` is a
  permission surface `core/staff.py` gates on, so a synced row would sit beside
  `is_applications_coordinator` as a second near-miss authorisation path. **Known
  consequence:** `Committee.public` defaults to `False`, so a committee created in
  the admin later badges its officers with no opt-in step — inert today (the
  Meeting of Analysts is the only Internal committee; Board and Programming
  Committee are both public, verified against the live directory), but "Internal"
  no longer implies "unbadged officers". Design:
  `docs/superpowers/specs/2026-07-29-applications-coordinator-badge-design.md`.

- **Advisor pool opened to all eligible analysts** (task #483).
  `accounts.advisor.eligible_advisors` dropped any analyst carrying an open
  `availability` span of `status="no"` for the `advisor` function. The intent was
  to stop a member picking someone who has said they aren't taking new advisees;
  the effect was that a member whose *existing* Advisor closed their door
  couldn't name them at all, because **the picker is the only way an advisorship
  gets recorded** and there's no prior `Advisorship` row to grant an exception
  from — at launch essentially every real advisorship predates the site. The
  filter therefore failed hardest on the intake survey's "Who is your current
  advisor?", which is *precisely* a request to record a relationship that
  already exists off-site. Declared availability is now **advisory**: it labels
  the picker instead of gating it. `advisor_availability_split` becomes
  `advisor_choice_groups`, returning ordered `(label, users)` groups —
  *Available to advise* (open `yes` span) / *Unknown availability* (no declared
  status: no open span, an explicit `unknown`, or a scholar-track advisor, who
  carry no spans) / *Not currently accepting new advisees* (open `no` span) —
  with empty groups omitted, query ordering kept inside each, and the labels as
  module constants so picker and tests can't drift. One open span per
  (profile, function) is a DB constraint, so the status map needs no precedence
  rule; a *closed* `no` span still reads as unknown. Both surfaces share it: the
  Formation-tab `AdvisorSelectForm` (whose `queryset` is now the wider pool, so
  the POST validates) and the intake survey's `<select>`, which gained the same
  `<optgroup>`s. **No block, no confirmation, no warning** — the group label is
  the whole disclosure (do-not-over-automate), plus one line of help text on both
  surfaces. `set_advisor` is untouched, so the chosen analyst is notified
  whatever they declared; for the already-advising case that notification *is*
  the record. The availability surfaces are unchanged —
  `/directory/availability/?only=advisor`, linked from the account-ready and
  acceptance letters as "currently available to advise", still lists only
  analysts who said yes. That page stays the recommendation; the picker is the
  record. Deliberately no `FormationSettings` toggle: "for now" is served by a
  revert, not by a field, a migration, and a branch to test both ways. Design:
  `docs/superpowers/specs/2026-07-29-open-advisor-pool-design.md`.

- **A requested payment plan covers events** (task #484). Applying for a
  payment plan is a request to the Board (`PLAN_REQUESTED` + a PENDING
  `TuitionPlanApplication`, task #450 phase B), and fall registration could
  not wait on the Board's turnaround. The hold was never a *block* — the
  enrollment row exists, so the broad no-decision gate was always satisfied —
  it was **pricing**: `PLAN_REQUESTED` was absent from
  `TuitionEnrollment.covers_seminars`, so `is_tuition_current()` was False, no
  `covered_by_tuition` tier resolved, and the member was quoted the full
  seminar fee. The charge side never agreed with that reading:
  `payments.charges._owed_periods` exempts only SKIPPING, so the year's
  tuition charge was minted regardless — the school treated the money as owed
  while withholding what paying it buys. `covers_seminars` now covers every
  non-skipping decision. Second, the **narrow special-event gate is deleted**
  (`TUITION_BLOCKING_EVENT_TYPES` + its branch in `_tuition_block_reason`):
  per Rico (2026-07-29), a tuition-eligible special event is waived for
  COMMITTED *and* PLAN_REQUESTED on the assumption tuition will be paid, which
  removes the one place where "committed but no money yet" had teeth —
  deliberately, and reversible by revert rather than by a flag. One gate
  remains: some decision must be on file. Also: a fully covered year reads
  "Paid" for a pending request (`payments/ledger.py`), the member's pending
  note and the Board's queue intro both say coverage is already live, and the
  decline notification warns that a $0 registration taken under provisional
  coverage may need settling (nothing unwinds automatically — do-not-over-
  automate). The treasurer guide's two-gate section and its case table were
  rewritten to one gate. No migration, no backfill, no flag; balances cannot
  move. Design:
  `docs/superpowers/specs/2026-07-29-plan-requested-seminar-coverage-design.md`.

- **Skipping a covered year re-bills the events** (task #485, follow-on to
  #484). #484 made coverage provisional in one direction, and nothing owned the
  other: a member who consumed coverage and then ended up SKIPPING owed nothing
  for those events, because a covered registration is created with
  `quoted_amount=0` and **no Payment and no Charge** (`mint_registration_charge`
  requires a positive amount), while SKIPPING is exempt from tuition charges.
  The Board declining a plan is only the rarest route in — the likelier one is a
  member who records COMMITTED, registers free, then re-records SKIPPING — so
  the mechanism keys off the *decision*, not the decline. New
  `payments/coverage.py` answers what coverage bought in a year
  (`covered_registrations`, which excludes comps and pricing-code freebies since
  neither is coverage), what it was worth (`retro_amount` — the tier's
  `base_amount`, or `minimum_amount` for a sliding tier, since a skipping member
  would have picked their own figure at or above the floor), and bills or
  un-bills it. **Billing re-quotes the Registration rather than minting a
  Charge**: `quoted_amount` + AWAITING_PAYMENT lights up the built "Pay →"
  Stripe button, the registration reminders, and `mint_registration_charge` at
  settle, where a bare Charge would have been unpayable — the member-facing
  payment endpoints are dues, tuition-in-full, installments, donations, and
  per-registration checkout, nothing else. A PENDING_APPROVAL row gets its
  amount rewritten but **keeps its status**, because `approve()` routes on the
  amount and flipping it would skip the faculty approval it awaits. Recording a
  paying decision un-bills, so **committing to pay restores event access without
  any money moving**; a fee actually paid is never unwound (treasurer's refund
  call). The member confirms on an interstitial listing every event, its fee, and
  the total before anything is recorded, and gets one notification after — built
  from the rows `bill_skipped_coverage` *returns*, since a stale in-memory copy
  still reads $0. Access loss while re-billed is accepted, deliberately: the
  routes back are the registration's Pay button and the tuition decision form.
  **Staff paths do not auto-bill** — admin, the treasurer's set-status,
  `backfill_tuition_status`, the importers — or a historical backfill would
  retro-bill years of events. No migration: the marker is the
  `quoted_explanation` string, held in `coverage.REBILLED_EXPLANATION` and pinned
  by a test, mirroring how `"Covered by tuition (tuition-paying member, REG-4)"`
  already identifies a covered registration. Design:
  `docs/superpowers/specs/2026-07-29-skipped-coverage-rebilling-design.md`.

- **School officers count as workgroup leads** (task #480). Verified on prod
  across all 30 workgroups, two had members and zero owners — meaning if anyone
  opened their video room, *nobody* got moderator controls (mute / camera-off /
  remove) and *nobody* got a Record button. The room worked; it was
  unmoderatable. For the **Meeting of Analysts** the cause was structural. The
  workgroups layer already treats the school officers as authoritative —
  `can_manage_workgroup` returns True for the President / Vice-President on
  every workgroup, and `participants()` synthesized them as the Meeting's
  leaders, so they *displayed* as its leadership. But that leadership is
  **derived** from `StaffRole` holders synced off the Board roster (task #428),
  never stored as a `WorkgroupMembership` carrying a `LEAD_ROLES` value, and
  four call sites re-ran the raw roster query
  (`memberships.serving().filter(role__in=LEAD_ROLES)`) instead of asking a
  predicate — so the roster asserted a leadership the permission layer didn't
  grant. New **`workgroups.permissions.is_workgroup_lead`** knows about both,
  and five call sites adopt it: `video.services.is_owner` (the Daily token's
  owner flag), `Recording._can_host`, `parletre.permissions._workgroup_lead`,
  `workgroup_has_leads`, and — not in the ticket — `channel_can_moderate`'s
  legacy committee-access branch, which resolves *only* for committees and so
  was the likeliest place for the bug to survive a fix aimed at it.
  **Scope is the Board and the Meeting of Analysts, nothing else** (Rico,
  2026-08-01): not the Programming Committee, not other committees, not
  cartels, seminars, reading groups or working groups. Narrower than *both*
  existing rules, deliberately — management authority and leadership are
  different claims, and the President may fix a cartel's roster without leading
  the cartel. Narrowness is also load-bearing: `workgroup_has_leads` feeds
  `can_register_decision`, where a **leaderless** group lets any active member
  record, so officers-as-leads-everywhere would have made every cartel lead-led
  and silently taken the decision register away from its members. The one
  behavior change beyond the room: the Meeting stops being leaderless, so
  recording a decision in *its* register narrows from any analyst to the
  officers plus managers — which is how the Meeting actually decides. **The
  orphan guard deliberately stays stored-rows-only** (`lead_members` /
  `_would_orphan`): the Board's stored Chair is the source of truth that syncs
  the President `StaffRole`, so a derived-aware guard would authorize removing
  the last Chair on the grounds that the President covers it — the very change
  that un-syncs the President. No superuser bypass in the predicate either; it
  answers who *leads*, and call sites keep their own `is_staff` clauses.
  `participants()` now shares the helper and **upgrades** an officer's entry
  rather than replacing it — a stored Board Chair keeps their membership and
  gains only the title, where the old code discarded the row, which is why it
  had to be restricted to the auto-membership Meeting. No migration, no flag.
  The other zero-owner group, **Working Group on Cartels** (6 members, no
  organizer), is `kind=working_group` and thus out of scope by the same
  decision: it is a data fix, appointing an organizer in its Settings roster.
  Design: `docs/superpowers/specs/2026-08-01-workgroup-lead-officers-design.md`.

- **Payment plans for a single seminar or reading group** (task #501). Seminar
  fees run $50–$900 (a $60/session seminar over fifteen sessions), and faculty
  held three discretionary levers for a member who couldn't meet one —
  percent-off, fixed-price, sliding floor — all of which answer *how much* and
  none of which answers *when*. `PricingCode` now carries an **`installments`
  count orthogonal to `pricing_mode`**, so "20% off, payable in three" and
  "full price, payable in three" are both expressible; making a plan a fourth
  `Mode` was rejected because `amount_or_percent` is money or percent in all
  three existing modes and would have had to mean a count in the one function
  documented as a place where a bug costs money. `Mode.FULL_PRICE` fills the
  no-discount case (rejected: a blank-able `pricing_mode`, which adds a null
  branch to `_apply_code`; and a `fixed_amount` code at the base price, which
  hardcodes a fee that later goes stale). **The total never changes** — the
  same discipline the tuition plan holds. The count is all faculty choose; the
  site splits evenly with the remainder on the **final** installment and
  **spreads the payments across the event's own run** — the span from
  registration to the event's end divided into `count` equal periods, one
  payment at the start of each, floored at `MIN_INTERVAL_DAYS = 28`.
  The first cut shipped monthly-from-registration and **bunched every payment
  at the front of a nine-month seminar** (caught by Rico, 2026-08-03); the
  AY-anchored Sept/Feb tuition shape doesn't transfer either. Spreading makes
  the school's own vocabulary fall out of the geometry — on the common Sept–May
  seminar two payments land fall and spring, four land two-and-two, nine land
  monthly — **without naming any of it**, which matters because named terms
  cannot describe two events in the real 2026-27 program: the four-week October
  workshop (`workshop-clinic-of-psychosis`, Oct 1–29) and the January–June
  reading group. The floor stops a short event getting a fortnightly debit, and
  the last payment always lands inside the run, so the school is paid before it
  finishes delivering.
  **The feature is small because the accounting was already there:** `Charge`
  carries a `registration` FK with a unique-when-not-void constraint, the
  ledger's `_charge_states` already returns `"partial"`, `Payment` already
  points at a registration with nothing limiting it to one, and
  `complete_payment` already flipped `AWAITING_PAYMENT → PAID` on the first
  payment — which *is* the access semantics a plan wants. So one registration
  stays one full-fee `Charge`, and the balance, statement, and reminders come
  out right with no new accounting. New: `payments.RegistrationInstallment` (a
  field-for-field twin of `TuitionInstallment`; unifying them would rewrite the
  #494 plumbing for no behavior gain), `Payment.registration_installment`, and
  `payments/registration_plans.py`.
  **Two existing behaviors were wrong and are fixed.**
  `mint_registration_charge` minted `payment.amount`, so a $500 seminar paid in
  three would have entered the books as a **$166.66 obligation**; it now bills
  `quoted_amount` for a plan registration, scoped so no ordinary row's
  provenance shifts. And `Registration.cancel()` refunded `.first()` succeeded
  Stripe payment and flipped to REFUNDED — with three installments that
  **under-refunds and calls the whole thing done**. That was a latent bug for
  *any* multi-payment registration, not only a plan; self-cancel now raises
  `PlanRefundRequiresTreasurer` and routes to the treasurer, because someone
  who attended four of ten sessions is a pro-rating conversation, not an
  arithmetic (§4.1). Rejected: refunding every installment automatically, and a
  before-the-first-session date rule.
  **The consequence worth stating: `Registration.status == PAID` now means
  *enrolled*, not *settled*.** The ledger is untouched (it reads charges and
  payments, never registration status), so the money is right from day one;
  what shifts is the reading of `PAID` on the registrar console's per-status
  counts and the roster CSV, both deliberately left alone. The disclosure is a
  neutral **"On a plan"** chip on the faculty roster — no amounts, no
  behind/current distinction, since faculty issued the plan and the roster is
  a surface they export to CSV and read in class. Note the roster that matters
  is the **Workspace `?tab=roster`**, not `?view=faculty`: a seminar's event
  page redirects to its Workspace, and `_faculty_tools.html` is shared by both,
  so `Registration.on_payment_plan` is a property and each context builder just
  prefetches. `outstanding()` quantizes because `Sum` hands back an unscaled
  Decimal — a $200.00 balance arrived as `Decimal("200")` and rendered as
  "$200" beside its own "$166.66" installments.
  A plan registration reads `PAID` and so was invisible to every existing
  nudge; `send_registration_reminders` gains a third kind on the same throttle
  field and host timer. **No automatic consequence for defaulting** — the lever
  stays the treasurer's `seminar_access_suspended`, human and audited. No
  autopay, no pro-rating, no faculty-authored dates, no new flag, no backfill.
  Design:
  `docs/superpowers/specs/2026-08-03-registration-payment-plans-design.md`.

- **A feature image on an event** (task #504). An event page was all type, while
  faculty routinely have a painting or a book cover in mind for the offering.
  Storing a file is the easy half; the hard half is that faculty upload every
  shape there is, and one layout has to hold all of them. **The shape is settled
  at upload, not at display** (`events/feature_images.py`), which is the
  `accounts/images.py` principle — normalize on the way in so every render site
  "just works" — departing from it only in allowing a **range** rather than a
  square: `1:1 ≤ ratio ≤ 2.5:1`, free-cropped in the vendored Cropper.js and
  re-clamped server-side, since a hand-rolled POST, a no-JS upload, and the
  whole-image default all bypass the drag handles. A single fixed ratio was
  designed first and rejected: it butchers a square poster. The render fits a
  1600×900 box (a 2.5:1 lands 1600×640, a square 900×900), WebP q82, alpha
  flattened onto white; the retained original — kept so the framing can be
  revised — is itself re-encoded to 2400 px WebP q88, so a 20 MB phone photo
  does not sit in S3 forever to make re-cropping possible. Refused: over 12 MB
  before decoding, and any render under 800 px wide, where the band shows a
  blur.
  **The layout rule is to bound both dimensions rather than fix the height**:
  never taller than the band, never wider than the column, and never asked to be
  both at once. So a 2.5:1 runs the full column, a square sits as a narrow plate
  beside white space, every event page keeps the same vertical rhythm, and
  nothing is re-cropped at display time. Verified in the browser at three
  shapes: the phone cap is the *looser* of the two (260 vs 340) because at that
  width anything wide is already column-bound, so the cap governs only the
  squarer end — at 200 px a square poster sat stranded.
  **It is edited by its own form posting to its own endpoint**, which is not a
  style preference: `event_edit_confirm.html:39` re-posts `EventEditForm` as
  hidden `<textarea>`s and a file input cannot survive that, so folding the
  image in would have silently dropped uploads on exactly those events that
  route through change review. That separation also makes its **absence from
  `REVIEWABLE_FIELDS` structural** rather than a remembered rule — and it is
  absent deliberately: review protects a description the PC approved, and there
  is no prior image to diverge from. Rights are a **condition of the upload**,
  not a field beside it: a structured source (public domain / licensed / own
  work / permission) plus a confirmation checkbox, both required, stamped with
  who confirmed and when, because a public page is where a takedown arrives.
  Surfaces are the event page, the Workspace masthead (via
  `Workgroup.primary_event()`, and note a seminar's event page *redirects*
  there), and a new OpenGraph block — the site emitted no social metadata at
  all before, so it is scoped to `event_detail.html` rather than pushed into
  `base.html`. WebP is served to scrapers directly; no JPEG twin. Two things
  found while building: Django refreshes `width_field`/`height_field` only when
  *replacing* a file, so a first upload inserted nulls, and the og description
  needs `inline_italics` before `striptags` or the member-text convention's
  `*asterisks*` reach a share card as punctuation. Nine fields went onto a new
  `OneToOne` `EventFeatureImage` rather than onto the 1,722-line `Event`, so
  absence of the row *is* "no image". Design:
  `docs/superpowers/specs/2026-08-04-event-feature-image-design.md`.

- **Opening the feature image at full size** (task #504, follow-on). Clicking the
  image opens it centred in a modal. Doing so exposed a resolution question the
  340 px band was hiding: the 1600×900 render is ample for the band even at 2×
  and visibly soft filling a modal, so `EventFeatureImage` gained a second
  **`image_full`** render at `FULL_BOX = (2400, 1350)` from the same crop, and
  `render()` grew a `box` parameter rather than being duplicated. The event page
  keeps serving the smaller file above the fold. Because `thumbnail()` never
  upscales, an upload between the 800 px floor and 1600 px would store two
  identical files, so the larger render is kept **only when genuinely larger**
  and a `modal_image` property returns `image_full or image`. Doing this now was
  the point: the feature had deployed minutes earlier with no event carrying an
  image, so there was nothing to backfill. Not the stored original, which is
  bounded to 2400 px and would seem the obvious candidate but is **uncropped**,
  so it would show what faculty framed out.
  The `<img>` is wrapped in a **real anchor** to the full render: with no
  JavaScript that opens the image directly, and it is focusable and
  keyboard-operable because of what it is rather than through added `role` and
  `tabindex`. JavaScript upgrades the click to a DaisyUI `<dialog class="modal">`
  (the house pattern), where `<form method="dialog" class="modal-backdrop">`
  gives click-outside and Escape is free — all three dismissal paths verified in
  a browser, Escape with a real key press since a synthetic `KeyboardEvent` does
  not trigger the UA default. **Two scrim traps, both found by looking rather
  than by reading the markup:** DaisyUI dims from `.modal[open]` (specificity
  0,2,0), so a bare `.lsp-lightbox` class silently loses and leaves its 40%
  black, which over the dark theme barely separates picture from page; and the
  caption must be a fixed light colour, since `text-base-content` in the light
  theme is near-black type on a near-black scrim. Both are plain CSS in
  `assets/css/input.css`, beside the `.hp-wrap` precedent. One latent bug caught
  by the tests: the new `box` parameter was shadowed by the existing local crop
  rectangle, feeding a 4-tuple to `thumbnail()`, so the local is now `crop_box`.
  Design: `docs/superpowers/specs/2026-08-05-feature-image-lightbox-design.md`.

- **Naming and enlarging the CE accreditors** (task #506). The CE panel showed
  accreditor logos as anonymous 48×144 thumbnails, and the ask was to name the
  organization and make the marks zoomable. Looking at the one accreditor on
  prod turned it into a data task too. *Greater Pittsburgh Psychological
  Association* carried a **single 645×360 file that was itself a composite** of
  three things: the APA Approved Sponsor seal, the GPPA wordmark, and — boxed
  beneath the seal — **the APA-mandated approval paragraph rasterized as tiny
  text**, while `statement` and `url` on the row sat empty. That paragraph is
  why the panel read as too small, and no zoom fixes it: the stored file is
  645px and **no original is retained for a logo**. The accreditor's original
  email attachments turned out to be exactly those three panels, so **two are
  logos and the third is the statement** — added as a third logo row it would
  keep every defect (unreadable at 189px, dark text on a *partly transparent*
  background so it half-vanishes on `abyss`, and unselectable, unsearchable,
  unreadable aloud, unreflowable).
  The panel now **groups per organization** — name, then its marks, then its
  statement — rather than pooling every logo in one row and every statement
  after them, which with two accreditors leaves each statement reading as if it
  covered both sets of marks. The outbound `org.url` link **moves from the logo
  to the name**, which is not cosmetic: it is what frees the image to become the
  click target. Chips grow to 64×192, and each is a **real anchor to its own
  file** (the #504 pattern — no-JS opens the image, focus and keyboard come from
  what it is), upgraded by one **shared** `<dialog>` per page, safe because the
  partial renders at most once (`_event_summary.html`'s `{% if %}`/`{% elif %}`)
  and scaling to N marks without N dialogs.
  **The modal image sits on a white plate**, not bare on the scrim as the
  feature-image lightbox does — verified in the browser, the GPPA wordmark is
  black-on-white and the APA seal's background is *fully* transparent, so
  either would vanish against `.lsp-lightbox[open]`'s 88% black. Same reasoning
  that already makes the chips `bg-white` in both themes.
  `ce_images.MAX_BOX` rose 800×400 → 1200×600: the incoming marks are squarish,
  so the old bound was actively **downsampling** them (459×431→426×400,
  605×548→441×400) and discarding resolution the zoom wants back. Two things
  found by the full suite rather than by the CE tests: a two-line `{# … #}`
  comment (Django's is single-line only, so line two would have leaked onto the
  page — `core/test_templates.py` enforces this), and two `test_ce_organization_add`
  cases that hardcoded the old box. Deliberately unchanged: the two *edit*
  surfaces keep their small chips, and CE stays out of `REVIEWABLE_FIELDS`.
  Design: `docs/superpowers/specs/2026-08-05-ce-logo-zoom-design.md`.

- **A PC-created program event is born unregisterable** (task #532). The Program
  Committee chair direct-created a late-addition seminar, set it to "Open for
  registration", and reported that the listings still read "Draft". He had
  missed no step: `Event.status` (Draft / Open / Closed) is the field on the
  add-event form, while **visibility for an annual-program type cascades from
  the owning `Program`** — which `Event.is_public_now` implements and *nothing
  else honored*. The badge, the Register CTA, the location block, the draft
  banner, the register gate, `upcoming.py` and the calendar feed all read the
  raw `Event.published` boolean, so the seminar was simultaneously public (per
  `is_public_now`, hence listed) and unregisterable (per the flag). The tell was
  sitting in the file: **`Program.public_program_year_q()`, written for exactly
  this cascade, was defined and never called from anywhere.** It stayed hidden
  because all fifteen sibling 2026-27 events were script-imported with
  `--publish`; only an event created through the *UI* exposes it, and
  `ProgramEventForm` does not expose `published` while
  `program_admin_special_event_publish` deliberately refuses program events —
  so **no button existed for him to press**. Replaced by `Event.public_now_q()`,
  which covers the non-program types too and has callers; the three querysets,
  five instance sites and a `published_count` that no template ever read now go
  through one predicate.
  **Underneath it, a deeper divergence:** `EventProposal.approve()` mints a
  *complete* event (price tier, meeting series, speakers) while
  `program_admin_event_new` mints a *bare* one. The PC's special-event
  direct-create had already solved this by routing through the proposal
  pipeline; the program-event path never got that treatment, so the same
  seminar also had **no price tier and no sessions** — unregisterable by two
  independent mechanisms, since price tiers had no UI outside Django admin.
  New `events/price_spec.py` is one definition of a price — the four values the
  proposal form always collected — with `from_event` / `apply_to_event` /
  `label`; `_build_price_tier` is refactored onto it so the paths cannot drift
  again. `PriceFieldsMixin` puts the app's **existing** Free / Fixed / Sliding
  vocabulary (`EventProposalForm.fee_type`) on the PC form and the faculty form.
  Deliberately *not* `mint_program_tiers`' fixed/donation/per-session: that is a
  one-off migration script's vocabulary, "donation" is just sliding-from-$0, and
  per-session is not in the model at all (the script pre-multiplied rate ×
  sessions into a fixed base) — adopting it would give the school two pricing
  vocabularies for one model.
  Price also joins `REVIEWABLE_FIELDS`, so a faculty price change routes through
  the certify-or-submit dialog. It is a *related row*, not an `Event` field, so
  it travels as a `PriceSpec` dict in two JSON columns and only `apply()` and
  `field_changes()` branch. Two traps: the price inputs would otherwise land in
  the view's `nonreviewable` list and reach
  `event.save(update_fields=["fee_amount"])`, and the confirm dialog's
  hidden-textarea re-post needed `tuition_covers` to follow the `record_video`
  checkbox precedent. **Two safety properties are requirements, not notes:** the
  spec addresses only the event-level `audience=ALL` tier, so an event with a
  student rate or session-scoped tiers renders **read-only** and
  `apply_to_event` *raises* rather than silently dropping a row; and a price
  change never touches `Registration.quoted_amount`, so nobody already enrolled
  is re-priced. Also deleted: `changed_reviewable_fields()`, dead *and* wrong
  (it read the event after ModelForm binding had mutated it in place) — a dead
  helper that silently disagrees with live code is what caused this bug.
  Design: `docs/superpowers/specs/2026-08-09-program-event-pricing-and-cascade-design.md`.

- **A form submits once** (task #545). The Referral Coordinator clicked **Send
  addendum** twice and the clinicians got two copies. `send_addendum` mails
  every clinician **synchronously**, so on a list of thirty-six that is seconds
  in which the button looks untouched — and nothing about that is specific to
  addenda. Every costly action here is a synchronous POST behind an ordinary
  button, and the one place already bitten (the public referral request on
  `find_an_analyst.html`) had answered it with a bespoke inline "Submit-once
  guard" written for that form alone. New `static/js/submit-guard.js`, loaded
  unconditionally from `base.html`, makes it the site's behavior: the first
  submit locks the form, later ones are swallowed, every submit button in it
  greys out and the pressed one shows a spinner.
  **Two things are load-bearing.** The listener is on `document` in the
  **bubble** phase, so it runs after a form's own handler — a form whose JS
  already called `preventDefault` (the Parlêtre chat's WebSocket path, the
  suggestions widget) arrives with `defaultPrevented` set and is skipped, so
  the escape hatch is automatic rather than a list to maintain; a form that
  only *conditionally* intercepts and this time falls through to a real POST
  is guarded, which is right. And **it never sets the `disabled` attribute**:
  the HTML form-submission algorithm fires `submit` *before* it constructs the
  entry list, so disabling the pressed button inside a submit handler drops its
  `name`/`value` from the POST. Twenty-eight buttons here carry a `name` — the
  treasurer's Reconcile approve/decline pair, the tuition plan queue,
  advancement, external-analyst and cartel decisions — so the obvious
  implementation would have traded a double-send bug for a whole class of
  silent no-op decisions. Buttons grey via a class (`pointer-events` stops the
  mouse) and the second submit dies on a flag (the keyboard, where Enter in a
  text field submits without touching a button). Every submit button in the
  form is greyed, not just the pressed one: *Approve* then *Decline* is worse
  than sending twice. `<a>` stays live, so Cancel still works.
  `.is-submitting` and `.lsp-spinner` are hand-written in `input.css` beside
  `.hp-wrap` for the reason `.hp-wrap` is — Tailwind v4 scans templates only,
  so a class emitted from JavaScript is stripped from the **production** build
  and nowhere else; DaisyUI's `loading loading-spinner` is out for the same
  reason (zero templates use it, so it isn't in the built CSS at all). The
  label is not swapped for "Sending…": re-flowing text moves more than the
  spinner does, and the label is what names the action still in flight.
  **No unlock-after-N-seconds failsafe** — it would re-open the double-send
  window at precisely the moment the response is slowest, which is this bug;
  the only reset is `pageshow`/`persisted`, since bfcache restores the DOM
  spinner and all. Deliberately no server-side idempotency token (Rico,
  2026-08-10): a nonce across 264 forms brings its own failure mode, a
  legitimate slow submit rejected as a replay. Verified in a browser: three
  clicks on a named submitter produce **one** POST still carrying
  `decision=approve`; intercepted and GET forms untouched; a simulated bfcache
  restore clears the lock. Design:
  `docs/superpowers/specs/2026-08-10-submit-once-guard-design.md`.

- **Recording a covering decision covers the registrations** (task #561). A
  member, after his tuition records were corrected: *"They all now say I am
  registered but awaiting payment?"* A registration is priced **once, at
  creation**, and both the pricing resolver (`_is_tuition_paying`, task #450
  phase A) and the ledger (`period_for_event`) anchor coverage on the **event's
  own** academic year. His four registrations were Sept–Oct 2026 events, so all
  four belonged to **AY 2026–2027** — the year that had not started yet — and
  each was created before any AY 2026–27 enrollment row existed, so each
  correctly stored the regular fee. Recording the covering decision afterwards
  changed nothing about them, for two independent reasons: `unbill_skipped_
  coverage` selected **only** rows whose `quoted_explanation` equalled the task
  #485 re-bill marker, and his said `'Standard All price.'`; and the status was
  set from the treasurer's surface, where `treasurer_tuition_set_status` called
  `coverage` on **neither** path. **The AY 2025–2026 edit that seemed to cause
  it was a red herring** — it cannot reach an AY 2026–27 event. The general
  case: **a member who registers before recording a covering decision keeps the
  full quote forever**, because #485 built the restore as an undo for its own
  billing rather than as an answer to "what does coverage owe this member now",
  so the one case it could not reach is the one that happened.
  New `coverage.apply_coverage` **replaces** `unbill_skipped_coverage` rather
  than joining it: a re-billed row is a **strict subset** of the structural
  predicate (covered tier, no pricing code, positive quote, AWAITING_PAYMENT or
  PENDING_APPROVAL, event in the period), so keeping both would leave the two
  directions able to disagree about what coverage bought — and matching the
  marker string is exactly what made this invisible. `REBILLED_EXPLANATION`
  survives as something written and read by humans; nothing matches on it. The
  covering check is made **once per call**, not per row: the loop already pins
  every candidate to the period, so one enrollment lookup *is*
  `is_tuition_current` for all of them.
  **Expiring the member's live Checkout sessions is load-bearing, not
  tidying** — at the moment his rows would have gone to $0 he had three open
  sessions worth **$1,360**, and a member returning to a stale tab pays for a
  place they now hold for free, with `complete_payment`'s settle guard minting
  no `Charge` against it, so the money lands as unattributed credit for the
  treasurer to refund by hand. `stripe_sync.expire_open_sessions` already
  existed for this hazard (written for cancel-then-re-register) and already
  refuses to abandon a session Stripe reports as **paid**.
  The two wirings are **deliberately asymmetric**. `tuition_decision` applies
  coverage and notifies (`notify_coverage_restored`, built from the rows the
  function *returns* — a stale in-memory copy still reads the old amount);
  `treasurer_tuition_set_status` applies it **silently** (Rico, 2026-08-11),
  because the treasurer is flipping historical years in the #443 cleanup. The
  treasurer path still does **not** re-bill on skipping: #485's staff-paths
  rule stands and matters more now, since retro-billing a cleanup pass would
  bill years of events. A row with money actually on it is excluded by the
  status filter — a fee genuinely paid is a refund conversation for the
  treasurer, never a silent unwind. No migration, no backfill, no flag; the
  four affected rows were repaired by hand on prod with these exact semantics
  before the code existed. Design:
  `docs/superpowers/specs/2026-08-11-apply-coverage-to-existing-registrations-design.md`.

- **Turning registration approval on for a running seminar** (task #564). The
  PC chair wanted `Event.requires_faculty_approval` on for a seminar that
  already had registered students, and nobody knew what that would do to them.
  The answer: nothing. The flag is read in exactly two places, both inside
  registration *creation* (`registrations/views.py:74`, and `:178` for the
  covered-by-tuition path), and nowhere else — so an `AWAITING_PAYMENT` row
  stays payable and a `PAID` row stays paid, and only registrations made after
  the flip queue. **That grandfathering is right and is kept**, but it was
  nowhere stated: it is an emergent property of where the flag happens to be
  read, the same shape of accident as #532's never-called
  `Program.public_program_year_q()`, so it is now pinned by test and said out
  loud in the help text. Retroactively re-queueing existing rows was rejected —
  it takes a place from someone who was told they had it, and would need their
  open Checkout sessions expired to be safe (#561's hazard).
  **Off was not the inverse of on.** Pending rows survived the flag being
  turned back off, `send_registration_reminders` kept nudging every three days
  about a queue the event no longer had a reason to hold, and clearing it meant
  deciding each row by hand to undo what was one checkbox to do. New
  `registrations/services.py::release_pending_approvals`, beside
  `comp_registration`, runs the same chain `approve_registration` does and
  **returns the rows it released** so the message is built from what changed,
  not a stale copy (#485/#561). It is idempotent because `approve()` returns
  False on a non-pending row. Both edit views call it on the True→False
  transition, reading the before-value **before the form binds** — `ModelForm`
  mutates the instance in place, which is exactly what made
  `changed_reviewable_fields()` silently wrong. **The Django admin deliberately
  does not fire it** (#485's staff-paths rule): a `post_save` signal would let
  any script that touches an event mail its registrants.
  **Faculty now own the switch.** It was PC-only, so the person running the
  seminar had to ask to change how their own registrations work. It joins
  `EventEditForm`, gated by `can_edit_event` so a reading group's conveners get
  it too, and **stays out of `REVIEWABLE_FIELDS`** — review protects content the
  PC approved, and there is no prior value for them to have approved. The trap
  is `event_edit_confirm.html`, which re-posts every field as a hidden
  `<textarea>` and so silently eats a checkbox; it joins the
  `record_video`/`tuition_covers` exception, or the toggle would be dropped on
  exactly the events that route through change review.
  **Two live defects surfaced on the way.** `registration_pending` notified
  `Event.faculty_members()`, which filters `role=FACULTY` — but a reading
  group's conveners hold ORGANIZER (#495), and `can_edit_event` has always let
  them approve. So on a convener-led offering the bell reached nobody and the
  email fell back to `SUPPORT_EMAIL`, the school's own inbox standing in for the
  person who should have been asked; new `events/permissions.py::offering_leads`
  is the audience for anything asking the people running an event to act, while
  `faculty_members()` stays as it is because "who teaches this" drives bylines
  and the roster. And the bell hardcoded `events:detail?view=faculty`, but an
  offering's event page **redirects** to its Workspace and drops the query
  string, landing faculty on Overview with no approve buttons; it now shares the
  email's already-correct `faculty_tools_url`. No repair migration was needed
  (`notification-url-denormalized`) because no event had ever carried the flag —
  verified, not assumed.
  Finally, the flag appeared in **no member-facing template**: the member learned
  their registration was under review on the confirmation page, after committing.
  One shared partial now says so on the event page's CTA, the register form, and
  the covered-by-tuition confirm page, which needs it most — one click straight
  to a pending row. The copy names no role, since a seminar's faculty and a
  reading group's conveners both review and the member need not know which. Only
  migration is the `help_text`. Design:
  `docs/superpowers/specs/2026-08-12-registration-approval-toggle-design.md`.

- **An event says who may register** (task #566). `Event.open_to_guests` said,
  in its own help text, that it "does not restrict who can register" — ticking
  it printed a guests-welcome note and did nothing else. Every gate the site
  had was about the registrant's obligations (the tuition decision) or the
  event's state; none was about whether the event was for members. It is now
  **`Event.registration_eligibility`**, *Members and guests* or *Members
  only*, and the name change is the point: a field named for messaging is how
  a restriction stays imaginary for a year. The flag had never once been
  unticked — all 28 prod events sat at the default — so the migration cannot
  change what any live event does, which makes the **default** the only
  consequential choice, and it stays open.
  **A guest is anyone `accounts.permissions.is_lsp_member` says isn't a
  member** — the one definition, deliberately wider than a role check (it
  admits Django staff, LSP Staff, and serving committee members whatever their
  role, and excludes the resigned and removed standings), so all three
  non-member roles are guests: Auditor, **Student, and Prospective Applicant**.
  A second, narrower predicate was rejected: the site would then hold two
  answers to "is this person a member".
  **The escape hatch is a code addressed to a person.** A guest holding a live
  `PricingCode` with `restricted_to_user` set to them registers normally,
  because the faculty member who minted it made the decision (§4.1). An
  *unrestricted* code does not open the door, however few uses it has left — a
  code that can be forwarded is not a decision about a person — which narrows
  the task #495 recipe on members-only events only, to one extra field on a
  form faculty already use. Rejected: a code box on the blocked page (a
  forwarded code admits any stranger) and staff-comp-only (faculty lose the
  self-serve route). The gate also passes anyone the event already treats as
  an insider (`can_edit_event` or `is_presenter`), or an outside speaker with a
  linked login would be told "members only" about their own evening.
  One predicate, `registrations.permissions.eligibility_block_reason`, shaped
  exactly like `_tuition_block_reason` (a member-facing string blocks, None
  admits), and **one enforcement point**, `register_for_event`, guarding right
  after it. It sits *after* the already-registered short-circuit deliberately:
  restricting an event later never disturbs a registration already taken, and
  un-registering someone is the registrar's call, not a side effect of an edit
  (the #485 staff-paths rule). Comp, the registrar console, and admin all
  bypass it.
  **The anonymous case is the one to get right**: the site cannot tell a
  signed-out member from a stranger, so an anonymous visitor keeps the Register
  button (it leads to login) under a note naming the restriction, while a
  signed-in guest gets the note *instead of* the button — a button leading to a
  403 is worse than no button. Two lines in the task #464 funnel promised what
  a members-only event can't honor ("You don't need to be a member to attend")
  and are now conditional.
  `visibility` and eligibility stay **independent** — who can see the page
  versus who can register, and `visibility` is admin-only, so they never appear
  side by side in the faculty or PC UI. The event page's guest note keyed off
  *both*, which was the old flag's emptiness showing through; eligibility drives
  it alone now, and the migration carries a members-only visibility across
  **once**, so an event that said members-only in the only way the site could
  keeps meaning it. Also: the field is out of `REVIEWABLE_FIELDS` (review
  protects the content the PC approved), and a test pins that its value
  survives the confirm dialog's hidden-`<textarea>` re-post, where a select
  needs no special case but a silent revert would be invisible. No flag, no
  backfill. Design:
  `docs/superpowers/specs/2026-08-12-registration-eligibility-design.md`.

- **A retitled offering renames its workgroup** (task #568). Faculty reported
  that his seminar's title edit "doesn't seem to be holding" — and that the
  punctuation differed between the program listing and the seminar page. Both
  were the same fact: **the title is stored twice**. `Event.ensure_workgroup`
  snapshots `self.title[:120]` into `Workgroup.name` at creation
  (`events/models.py:898`) and nothing ever re-derived it. The program listing
  renders `Event.title`, so it showed his edit; but a seminar's event page
  **redirects to its Workspace** (`events/views.py:298`), whose masthead renders
  `workgroup.name` — so the page he was actually looking at showed the pre-edit
  string, as did the three auto-provisioned Parlêtre channels, whose names *and*
  descriptions are derived from the workgroup name in turn. Verified on prod:
  `Event.title` carried the comma he asked for, `Workgroup.name` and all three
  channels did not. His edit had landed the whole time.
  The Changes tab being empty was a **red herring and is correct**:
  `requires_change_review()` needs an approved originating proposal, and the
  2026-27 program was script-imported (`from_proposal: []`), so a title edit
  saves straight through and writes no `EventChangeRequest` — there are **zero**
  rows site-wide.
  The cascade hangs off **`Workgroup.save()`, not off the callers**: `name` has
  several edit surfaces (the cartel details form, the Workspace Overview form,
  Django admin) and a rule enforced at call sites only holds until the next one
  forgets — the #532 lesson. `from_db` remembers the loaded name so `save` can
  send the new **`workgroups.renamed`** signal carrying `old_name`, which a
  listener needs to tell a *derived* string from a hand-edited one; the stored
  name is re-tracked after every save so an instance created and then renamed in
  one process (an import script) still cascades. `Workgroup.rename()` is the
  convenience wrapper that skips an empty/unchanged write and returns whether
  anything changed. Parlêtre listens and rewrites each channel's name and
  description **only where it still equals what the old workgroup name derived**
  — `Channel.name` is admin-editable, and a deliberately renamed room must not
  be silently reverted; provisioning and renaming now share one
  `derived_channel_text` definition rather than two that drift. Channel and
  workgroup **slugs are never touched** — they're the URLs.
  Which workgroup follows which title is decided by **`primary_event()`**, the
  same event the Workspace features, not by whichever row was last saved: an
  offering workgroup can carry several years' events, so editing a *past* term's
  title must not rename a continuing seminar. That predicate is also the guard
  that matters most — it returns `None` for non-offering kinds, so a special
  event can never retitle the **Program Committee's** workgroup that it shares.
  Unlike the billing side-effects of #485/#564, the sync deliberately **does**
  fire on the staff paths (Django admin, the import scripts): renaming sends no
  mail and charges nobody, and the stale copy is what faculty see. The `Event`
  receiver skips any `save(update_fields=…)` that doesn't write `title`, which
  is how the faculty edit form's non-reviewable partial save and
  `EventChangeRequest.apply()` both stay cheap and correct.
  `manage.py resync_workgroup_names` (`--dry-run`) is the one-time sweep for
  rows that drifted before the sync existed; it calls
  `sync_name_from_primary_event` rather than re-deriving the name itself.
  A prod-wide scan for the stale string found exactly one drifted workgroup and
  its three channels. Three `notifications.Notification` titles also hold it and
  are **deliberately left alone** — they record what the event was called when
  the member registered, and unlike the denormalized `Notification.url` (which
  was *broken*) a historical title is not wrong. No migration, no flag. Titles
  themselves still render plain: `inline_italics` covers description, readings,
  and the notes, never `title`, so a lowercase-italic *or* isn't expressible —
  the comma is the answer.

- **The date the school is in, not the one UTC is in** (task #571). Found while
  investigating #568. `timezone.now()` is UTC-aware, so **`.date()` is the UTC
  date** — while every plain `DateField` here (`end_date`, `due_date`, period
  boundaries) is a date in the school's own timezone. Django sets the process
  timezone to `settings.TIME_ZONE`, so `datetime.date.today()` is Pacific **on
  the CI runner too**, and from 17:00 Pacific until midnight the two disagree by
  a day. The live symptom was `event_list` filtering
  `end_date__gte=timezone.now().date()`: **an event ending today dropped off
  `/events/` seven hours early, every evening** (fixed first, in 039b975, to
  unblock a deploy). `landing_events` had the same shape, so the landing page's
  "Coming up" list lost it too.
  All **56 remaining call sites** are now `timezone.localdate()` — every one of
  them meant "today" to somebody in the school. The ones that could cost money
  were `payments/charges.py`, `coverage.py`, `ledger.py` and `emails.py`, where
  the boundary decides what is **owed, overdue, or covered**:
  `sync_dues_charges` refuses a future period so next year's members don't show
  as owing early, and on the UTC date **tomorrow already qualified**. The audit
  stamps matter for a different reason — `[{date}] …` lines in `staff_notes` are
  read by the treasurer as *when did this happen*, and after 5pm they said
  tomorrow. Migrations keep what they were written with: they are historical and
  already applied, so editing one changes nothing that has run.
  **Tests were swept too, and not for tidiness:** a test building a date from
  `timezone.now().date()` and asserting against code that uses `localdate()`
  disagrees for those same seven hours, which is a flake that looks like a
  regression in whatever branch is merging. `test_create_accepts_today` proved
  it — it posts "today" to a view that rejects future dates, and after the sweep
  it was posting *tomorrow*. It also caught the sweep's own gap: it says
  `djtz.now().date()`, an aliased import the first pass missed, which is why the
  guard matches `now().date()` rather than the module name.
  **The guard is the point of the task**, not the substitution. This class of
  bug fails CI only on runs started between 00:00 UTC and 17:00 Pacific, so a
  green run earlier in the day proves nothing and the next instance lands
  exactly the way this one did — looking like the fault of the branch that
  happened to be merging. `core/test_local_dates.py` greps the tracked tree
  (`git grep`, so sibling `.claude-worktrees` checkouts aren't swept) and fails
  on any reintroduction; it was verified by reintroducing one. Beside it, four
  behavioural tests freeze the clock at **00:30 UTC = 17:30 Pacific** and pin
  the boundary directly, plus one test asserting that the frozen instant really
  does straddle the date line — without it, the other four could pass while
  proving nothing.

- **Replacing a document, and remembering what it was** (task #592). The board
  sent new formation guidelines and there was no way to put them on the site
  except the Django admin: find the row, upload into `file`, remember to fix
  `effective_date` by hand. Two costs. **The prior file became unreachable** —
  Django has not deleted a replaced `FileField` target since 1.3, so the old
  PDF was still in the private bucket under its old key, but nothing pointed at
  it, nothing recorded that a swap happened, and nothing said who did it. The
  scholar guidelines had carried `effective_date=2023-01-09` since seeding.
  And **documents were the one piece of editable site content with no home
  under `/admin-tools/`** — the Web Coordinator admin had been rendering a
  *Planned* card reading "Site documents" since it was built
  (`web_coordinator.html:12`); this fills that slot. Not `superseded_by`,
  which links two *different* `Document` rows, is public, and across 23
  production documents **has never once been used**: it answers "a different
  document replaced this one", not "this document's contents changed".
  The surface is **role-based, not object-based** — a first cut put the editor
  and the history on the public document page, which is the ergonomics the ask
  described but the wrong shelf (Rico, 2026-08-15): every admin area here is
  organised by the role that owns the work. So management lives at
  `/admin-tools/web-coordinator/documents/`, and the public detail page keeps
  exactly **one gated deep link**. That relocation is also what makes the
  invisibility requirement *structural*: the history renders on an admin
  template a non-holder cannot reach, rather than behind an `{% if %}` a later
  edit could get wrong. Gated to `WEB_COORDINATOR` alone — pairing in the Web
  Developer (the pattern `suggestions/permissions.py` uses) would grant a child
  page to a role that 403s on its parent hub.
  **A revision is the state *before* one save**, so each row reads "the
  document used to be this" and the live state is never duplicated — which is
  also why the 23 existing documents need no backfill: the first edit captures
  the original for free. Snapshotting *after* each save would have needed a
  synthetic baseline row or lost every original. "What changed" is computed,
  not stored (`changes_against`, pairing each revision with its successor and
  the newest with the live document). The file is **referenced, never copied**:
  assigning the storage key points two rows at one immutable object.
  `Document.snapshot_revision` **re-reads its own row from the database** rather
  than trusting `self`. That is not defensive habit — a `ModelForm` mutates its
  instance in place during validation, which is what made
  `changed_reviewable_fields()` silently wrong in #532 and what #564 had to
  work around by reading the before-value ahead of binding. Re-reading means no
  call site has to remember the rule, and a test pins it directly.
  **The Django admin deliberately *does* fire the snapshot**, departing from the
  staff-paths rule of #485/#564 — that rule stops admin edits from mailing
  members or moving money, and a snapshot does neither. What it prevents is a
  history reading "no revisions" while the PDF has in fact been swapped, and a
  partial history is worse than none because it is trusted. `save_model` is
  also the one admin hook that knows who is acting.
  Restore is **forward-only**: the current state is snapshotted before the old
  one is written back, so restoring is itself an edit in the history and nothing
  is destroyed. Two traps handled en route: `display_order` has a default but no
  `blank=True`, so a `ModelForm` makes it **required**
  (`new-modelform-field-is-required-by-default`); and `admin_sections` in
  `core/staff/admin/_base.html` renders inside a two-column grid, so a table and
  a form belong in `admin_after_header`. Identity fields — slug (the URL, with
  no redirect), category, owning workgroup, authors, `superseded_by` — stay in
  Django admin, as does creating a document. Verified in a browser at both
  pages. Design:
  `docs/superpowers/specs/2026-08-15-document-replacement-and-revisions-design.md`.

- **A decision form that never named its year** (task #599). A new
  pre-candidate, admitted 2026-07-27: *"There's an error on the website when
  trying to register, even though I have paid the tuition, and previously had
  done the 'record your tuition decision'."* Not an error — the 403
  `blocked_tuition.html` page, saying *"record your tuition decision for AY
  2026–2027"*. She had recorded one, and paid $2,500 for it, **against AY
  2025–2026**: her enrollment, its installment, the minted `Charge` and the
  Stripe payment all sat on the year that ends 2026-08-31, a year she was
  never a member of. The registration gate keys off the **event's** academic
  year (`period_for_event`), so every 2026-27 seminar asked her for a decision
  she believed she had made, while every 2025-26 event let her through.
  **The Account tab renders two decision forms**, current and upcoming
  (task #450 phase A). The upcoming one is headed *"Your AY 2026–2027 tuition
  decision"* and posts `period=<slug>`; the current one had **no heading at
  all** — its legend was the form's own field label, `"My decision for this
  academic year"`, and its three options said *"this year"*
  (`payments/forms.py:66-77`). In August "this academic year" means the year
  about to end. It is also the form both prompts point at: `blocked_tuition`
  linked to a bare `?tab=account`, and the walkthrough checklist anchors
  `#decision`, which is the section, i.e. the top block. So the site named a
  year, then sent her to an unlabeled form for a different one.
  **Why only her.** Every other decision recorded since registration opened
  (22 rows from 2026-07-23) landed correctly on AY 2026–2027, because those
  members already had a 2025-26 row — the top block showed them a summary of a
  decision already made, and they scrolled to the labeled one. A member with
  no history is the case that meets two empty forms and fills the first.
  The fix names the year in both places it was missing: `TuitionDecisionForm`
  takes an optional `period` and rewrites the label and all three choices
  through `choices_for(period)` (the POST path builds the form only to
  validate, with no period, and the *values* never change, so validation
  cannot depend on it); the current block gains the heading and an end-date
  line the upcoming block's shape already implied. Each block is then
  **anchored per year** (`#decision-<period.slug>`, the section's `#decision`
  kept for the checklist), and `register_for_event` passes
  `period_for_event(event)` to the blocked page so its link lands on the form
  for the year it just named. Deliberately *not* reordering the blocks or
  hiding the ending year: a member legitimately still records and pays 2025-26
  through August.
  **Her data was repaired on prod first** (enrollment 261 moved to AY
  2026–2027). Moving it was enough on its own: `payments.signals` fires
  `sync_tuition_charges` on enrollment save, which minted the AY 2026–2027
  charge and voided the 2025-26 one by itself — the manual charge edit beside
  it was redundant and had to be undone. Balance unchanged at −$50 (her dues
  credit), `tuition_years_covered` still 1, no ledger conflict, and the
  covered-by-tuition tier now resolves for the 2026-27 program. Left standing:
  her $50 dues also filed under AY 2025–2026, which is harmless — the dues
  bucket is category-scoped and oldest-first (#473), so it will cover her
  2026-27 dues charge when one is minted. Also noted, not fixed:
  `TuitionEnrollment.source` defaults to `STAFF` and `tuition_decision` never
  overrides it, so a member's own decision reads as staff-recorded.

- **An online event says where online** (task #624). Gardner, teaching a seminar
  this term, asked whether the site's video room was meant for class meetings —
  he wants screen sharing and breakout groups and would rather stay on Zoom "to
  minimize technical snags." The answer was *yes, but the site will fight you
  about it*, which nobody knew because nothing could record the case.
  `Event.access_info` has always carried an external link and released it to
  paid registrants, but `Event.format` says *whether* people gather in a room
  and never *which*: `EventProposal.LocationKind` offered in-site / in-person /
  hybrid, and the mint writes `access_info=""` for online. So an event meeting
  on Zoom showed its students **two doors, one opening on an empty room** —
  `_event_summary.html` renders `_location.html` (a Join button gated only on
  the *global* `daily_enabled()`, never consulting `access_info`) at line 101,
  and "Your access details" with the Zoom link at line 122. The confirmation
  email was worse: `payments/emails.py` set `room_url` on `has_access and
  daily_enabled()` with **no format check at all**, so *in-person* registrants
  were mailed "Join the meeting room (in your browser, no app to install)" —
  a live defect independent of the ask, fixed by the same predicate.
  New `Event.online_venue` (`insite` / `external`) is orthogonal to `format`, so
  a hybrid event can gather in a room *and* meet on Zoom, and everything asks one
  property, `uses_insite_room`. **Deriving it from `access_info` was designed and
  rejected**: the mint writes a hybrid event's *venue address* there
  (`models.py:1581`) and a hybrid event still wants the room, so the guess would
  have silently taken the room from every hybrid event — #532's lesson about a
  fact each surface re-derives. The same heuristic **is** safe run once, where it
  can be inspected and never fires again, so the migration carries
  `format == online AND access_info != ""` across to EXTERNAL (#566's precedent).
  **Faculty own the venue; the PC owns the format.** Neither `access_info` nor
  `format` was on `EventEditForm`, so the person teaching the seminar had to ask
  the PC to set their own meeting link. `online_venue` and `access_info` join it
  (gated by `can_edit_event`, so conveners get them too); `format` stays PC-only,
  since whether an offering gathers in a room is a program-level fact. Both are
  out of `REVIEWABLE_FIELDS` — review protects the description the PC approved,
  and a meeting link was never approved content. A `<select>` and a `<textarea>`
  both survive the confirm dialog's hidden re-post (only checkboxes need the
  exception list), pinned by test. `EventProposal.LocationKind` gains
  `ONLINE_EXTERNAL`, and the mint's existing `access_info = self.location if
  location_kind != ONLINE_INSITE` line carries the link with no change;
  `location` stays optional, because faculty proposing in spring rarely have
  autumn's Zoom link. **The trap the spec predicted and the first pass still hit
  in one of two places:** a choices-plus-default field is required by default on
  a ModelForm, and applying `required=False` to `EventEditForm` alone broke six
  `ProgramEventForm` tests.
  **Breakout rooms are now on** (`enable_breakout_rooms` in
  `_desired_properties`, which #475 made the single source of truth `ensure_room`
  reconciles against, so existing rooms pick it up at next join with no
  backfill). Daily requires Prebuilt (what we run) and an *owner* in the call;
  `is_owner` is `can_edit_event` / `is_workgroup_lead`, so faculty and leads get
  the control. Daily documents it as beta. Screen sharing needed nothing — it was
  always Prebuilt's default. The faculty guide's access section is rewritten as
  two paths with what each gives and costs.
  **The Workspace Meet tab deliberately stays** for an external event: the room
  belongs to the *workgroup*, not the term. Known and accepted: setting the venue
  back to the site's room while leaving a stale link in Joining details shows
  both again — that is the faculty member's own data, not the site guessing.
  **Two more instances of the same defect were found by grepping the remaining
  "meeting room" copy** once the page and the email were fixed: the outside-
  speaker invitation said "You will find the meeting room right there, no
  separate link needed", and the activation page said they'd land where they can
  open the room — both unconditional, so a special event on Zoom told its speaker
  to look for a room it doesn't use. Both now branch on `uses_insite_room`.
  Verified in a browser at both venues with video genuinely on
  (`DJANGO_DAILY_ENABLED`, not `DAILY_ENABLED` — the env var and the setting have
  different names, and the first check was meaningless because of it). Design:
  `docs/superpowers/specs/2026-08-20-online-venue-and-zoom-path-design.md`.

- **Paying before the year starts** (task #625). A candidate wrote in: *"how to
  submit payment on the new website? It seems that perhaps the portal is not
  available until Sep 1 but I would like to pay now."* He was right, and the
  reason was one clause. The Account tab's next-year tuition block is guarded
  `{% if owes_tuition and upcoming_period and not decision_exempt %}`, and that
  block holds the **pay** form as well as the decision form — while the decision
  form *inside* it already carried its own `{% if not decision_exempt %}`. The
  inner guard was the one that meant something; the outer copy of it took the
  pay button with it. And `tuition_decision_exempt` fires at **four non-skipping
  enrollment rows** (`payments/ledger.py:463`), which for him were three paid
  years plus the AY 2026–2027 `committed` row itself — so **recording the fourth
  commitment is what removed his ability to pay it**. The current-year block's
  pay button is *not* gated that way, so the button would have reappeared by
  itself on September 1 when the year became `current()`: "not available until
  Sep 1" was literally true and entirely accidental. Measured on prod before
  touching anything: **9 members committed to AY 2026–2027 with an open $2,500
  charge and no button anywhere on the site, $22,500** — the treasurer among
  them, which is why writing to him hadn't helped either — against 2 committed
  members who could pay, the two cohorts differing by nothing but how many
  enrollment rows they happened to have. The backend was never broken:
  `_resolve_tuition_period` already accepted the upcoming slug and
  `test_pay_in_full_for_upcoming_period_binds_to_upcoming_not_current` already
  pinned it. Nothing was missing but the button.
  The guard becomes a **view flag**, `show_upcoming_tuition`, precisely so the
  two conditions stop looking alike: the block renders when there is something
  to decide **or** something to pay (`upcoming_enrollment or not
  decision_exempt`), so an exempt member with no row for next year still gets
  nothing rather than an empty heading. Also found and filled: `upcoming_
  installments` was computed in the view and rendered by no template, so an
  **approved plan for next year** would have had rows in the database and no way
  to pay them — inert today, but four plan applications are pending with the
  Board.
  **Dues had the same shape and no fix at all.** `/dues/` was hardwired to
  `DuesPeriod.current()`, there was no `DuesPeriod.upcoming()`, and
  `dues_already_paid.html` told members outright that "The next cycle opens
  after that" — the sentence that reads as *the portal is not available until
  Sep 1*. Dues now mirrors tuition: `DuesPeriod.upcoming()`, a
  `_resolve_dues_period` validating a POSTed slug against `{current, upcoming}`
  (an unknown slug falls back to current rather than binding money to an
  arbitrary year), and the offer rendered on `/dues/`, on the paid-up page, and
  on the Account tab — **each naming its year**, per #599.
  Two traps, both money-shaped. `dues_state` is hardwired to
  `DuesPeriod.current()` (`payments/ledger.py:247`), so the already-paid
  short-circuit, left unscoped, told a **paid-up** member that next year was
  settled too and swallowed the very POST they had just asked for — this bug's
  own dead end, rebuilt inside its fix; the guard is now per-period, with the
  FK-bound `has_dues_payment_for` carrying it for any year but the current one.
  And an early payment has **no charge**, because `sync_dues_charges` refuses a
  year that has not started, deliberately — next year's members must not read as
  owing early. But a member who *chose* to pay early is not next year's members,
  and without a charge their money sits as loose dues credit for as long as the
  gap runs. So `mint_dues_charge` mints at **settle**, from `complete_payment`
  (the one chokepoint the Stripe webhook and the treasurer's "Apply payment
  success" both route through), exactly as `mint_registration_charge` already
  does one function above it: the obligation is created by money arriving rather
  than by a calendar, and the bulk refusal stays untouched for everyone who has
  not paid. It bills the **year's tier rate, not the amount paid** (a part
  payment must not shrink the obligation), returns any existing non-void row so
  the sync and the settle path can never double-mint, and mints only for members
  `sync_dues_charges` would itself have covered, so a voluntary payment from a
  non-obligated member stays a credit rather than a debt they never owed.
  Finally the dues Checkout line item names the period, or an early payment's
  receipt would not say which year it bought. No migration, no flag, no backfill.

Milestones 7–8 then cover production deploy + Swales &amp; Hook dry-run
(M7 — we're already on prod, so M7 is mostly data load + dry run) and
opening fall registration (M8).

**Phase 2 features already built and deployed (pulled forward — see the
Phase 2 plan for milestone IDs):**

- **Parlêtre** (`parletre`, MEM-3 / M13.5) — bespoke members-only
  discussion board at `/parletre/`. Multi-channel forum + realtime chat
  (Django Channels + daphne), channel access modes Open / Role /
  Committee / Private (private is private even from staff), reactions,
  @mentions + notification bell, unread tracking + jump-to-unread,
  attachments, per-channel subscriptions + email digests, reply-by-email
  (SES inbound → SNS → webhook, HMAC tokens; on a test domain pending
  the DNS migration), full-text search, editable/deletable posts +
  replies, and disappearing-message channels that **redact** on expiry
  (blackout text + black-box attachments) via `lsp-parletre-purge.timer`.
  Decorative glyphs use an inline-SVG `{% icon %}` tag. See
  `discussion-board` memory.
- **Workgroups** (`workgroups`) — shared collaborative layer; attach one
  Workgroup to cartels / committees / working groups / seminars / reading
  groups and the
  roster + Parlêtre channel gating live on it (`Channel.workgroup`,
  `access=workgroup`). `Workgroup.Kind` has five kinds (cartel,
  working_group, committee, seminar, reading_group). `/groups/` is a
  per-kind overview; each kind has its own index at `/groups/<kind>/`
  (`workgroups:kind_*`). **Add features to the Workgroup first.** See
  `workgroups-architecture` memory. The Workspace (`/groups/<slug>/`) is a
  tabbed surface driven by capability toggles — **every toggle is now backed
  by a real feature**: Overview, Discuss + Chat, **Work** (see below),
  **Files** (versioned shared files; 30 MB/file, 200 MB/group quota raisable
  in admin; private-S3-stored, gated download), Schedule (meetings/series/
  iCal), **Minutes** (the meeting record — minutes + the decisions from each),
  Tasks, **Decisions** (lightweight register; leaders record, or any member in
  leaderless groups like cartels; linked to the meeting that produced them),
  Roster, Settings.
- **Work-tab document editor** (`works.WorkDraft`/`WorkDraftVersion`) — a
  collaborative document center on each Workgroup's Work tab. Three draft
  kinds: a native in-browser editor (vendored TipTap — `npm run build:js` →
  `static/js/vendor/doc-editor.js`; autosave + version history + soft edit
  lock), a linked Google Doc, or an uploaded PDF (static until published).
  **Publish → Works** renders/attaches a PDF (fpdf2, DejaVu Unicode fonts,
  provenance title block) + a sanitized HTML body, bylined to the group's
  members; unpublish/delete supported. Comments/track-changes deferred
  (TipTap Pro). See `document-editor` memory.
- **Video / Daily.co** (`video`) — in-site, browser-based meeting rooms (Daily
  Prebuilt, no client install). One persistent `DailyRoom` per **Workgroup** *or*
  per Parlêtre **Channel** (board video channels), provisioned lazily on first
  join; private + per-user meeting-token gated. Surfaces: a Workgroup **"Meet" tab**
  (Meet Now + joinable meetings), a third Parlêtre channel kind **VIDEO**, and
  **context-aware event location** ("Online · video meeting"; live-gated Join).
  **Real Daily presence** ("Live now · N in the room", cached `GET /presence`)
  lights the Meet/Overview tabs, board channel tiles, and event pages. **Tech
  check** at `/video/system-check/` (throwaway room, auto-closes ~10 min). Hosts
  (faculty/leads) moderate via Daily's People panel (mute / camera-off / remove);
  everyone gets chat. **Recording is opt-in** (`video.Recording`): off until a host
  starts it, `Event.record_video` auto-starts; owned-S3 storage + gated playback +
  Works-style visibility + 1yr retention; hosts can delete/annotate a recording and
  a per-Workgroup/Channel `recording_mode` removes the Record button entirely (The
  Gaze is off). **Feature-flagged OFF** until `DJANGO_DAILY_ENABLED=true` +
  `DAILY_API_KEY`/`DAILY_DOMAIN` on the host. `daily.js` is vendored (see the CSS/JS
  pipeline note above). See the `video-daily-integration` + `video-recording` memories.
- **Cartels** (`cartels`, CART-1/2/3) — built on the Workgroup layer.
- **Directory** (`/directory/`), **Find an Analyst** map, member
  self-service **profile editor** (`/accounts/profile/`), **works**
  showcase (`/works/`), and **documents** (`/documents/`) — all live.
  `Work`/`Document` visibility is two-axis: `listing_visibility` (catalog) +
  **`content_visibility`** (the PDF *and* the published HTML body; renamed
  from `pdf_visibility`). Gated content lives in the private S3 bucket and is
  served only via access-checked download views — see `media-storage` memory.
- **Notifications center** (`notifications` app) — site-wide in-app bell
  (shown for every signed-in member, not just Parlêtre) backed by one generic
  `Notification` model. A single chokepoint, `notifications.dispatch.notify()`,
  creates the bell row and sends a preference-gated email (`transaction.on_commit`;
  rich app templates passed as `email_fn`, generic fallback otherwise).
  Per-category user controls at `/notifications/settings/` (in-app × email
  matrix); transactional categories — receipts, registration confirmation,
  sign-in/security mail — are email-locked. Every email-sending domain
  (payments/registrations, cartels, admissions, accounts) routes through a
  `<app>/notifications.py` wrapper, and group activity (membership, meetings,
  decisions/minutes, recordings) is in-app-first. Parlêtre migrated off its own
  notification model (old rows data-migrated; `parletre:notifications` redirects
  to `/notifications/`); its per-channel subscriptions + digest cadence stay.
  The bell is a **live dropdown** — a `BellConsumer` WebSocket
  (`/ws/notifications/`, over the existing Channels/daphne stack) pushes the
  unread count to open tabs; the panel lazy-loads recent items and marks them
  read on click. Email has a third **digest** option per category: items routed
  to *In a digest* still ring the bell immediately but their email is held and
  rolled into a daily/weekly digest by `manage.py send_notification_digests`
  (cadence on `NotificationPreference`; `Notification.digest_pending` flags held
  rows). See `notifications-center` memory.
- **Referral Coordinator workflow** (`referrals`, task #229) — Diana's
  email-shuffle moved in-site. Every Find-an-Analyst submission becomes a
  tracked `ReferralRequest` (date-based reference, Diana's convention:
  `26-0612` + `-2`/`-3` same-day suffixes, status
  lifecycle NEW → ACKNOWLEDGED → DISTRIBUTED → REPLIED/CLOSED), managed from
  `/admin-tools/referrals/` — gated to the new **`referral_coordinator`
  StaffRole + superusers only** (deliberately *not* generic `is_staff`;
  requests carry sensitive disclosures). The referral list lives in-site
  (`ReferralListMember`; clinician practice info is **self-service via the
  profile editor**, with a coordinator `details_override` escape hatch).
  Distribution reaches each clinician individually (bell + email, new
  `REFERRAL_REQUEST` notification category) with name+email withheld;
  responses attribute on an in-site respond page and aggregate on the
  request; the step-5 follow-up auto-assembles the right template variant
  (none/one/many) with each available clinician's details. **Every outgoing
  message is an editable `MessageTemplate` seeded verbatim from Diana's
  wording** (`referrals/seed_templates.py` — do not paraphrase), and **each
  sending step has a per-step auto/review toggle** on the
  `ReferralSettings` singleton (defaults: ack auto, distribution review,
  follow-up review, onboarding auto) per do-not-over-automate. New-member
  onboarding ("New Member Instructions", reworded to point at the profile
  editor) fires on list-add. `manage.py process_referrals` (daily host
  timer at launch) sends due auto-followups + redacts requests
  `retention_months` after reply/close. `DJANGO_REFERRALS_EMAIL` now a real
  setting. See `referral-workflow` memory.
- **Unified member ledger** (task #439) — replaced the per-category
  (dues/tuition/registration) treasurer views with one account per member:
  `payments.Charge` (debits) swept against `Payment` (credits) in
  `payments/ledger.py`, minted by `payments/charges.py`. The treasurer admin
  is now 7 tabs — Overview (AY tiles + one needs-attention queue), **Accounts**
  (every member's balance, linkable filters), Payments, Reconcile (provisional
  payments + no-payer + charge conflicts), Settings, Exports (+ a balances
  CSV), Help — with a per-member account page (statement, running balance,
  add/adjust/waive/void charge, record any-category offline payment). History
  minted via `manage.py backfill_charges`; `manage.py audit_ledger` is the
  read-only parity check. `user_paid_for_period` is retired. See
  `tuition-cumulative-ledger` memory.

## Open items (M7 wrap-up)

- **Un-mask the remaining 19 Google Group members.** The lsp-members group has
  84 subscribers; 64 are matched to the public directory and 1 is a fuzzy
  candidate (Ayelet Amittay's wildgeesementalhealth.com address). The other
  19 are masked (e.g. `dr.pete...@gmail.com`, `volc...@gmail.com`) and almost
  certainly admin/staff/aliases or members we don't have data for. A GG
  Workspace admin can export the un-masked list at
  `admin.google.com → Groups → lsp-members → Members → Export`. Once we have
  it, re-run the matcher in `import-staging/` to identify any additional
  dual-email cases, then `import_users --update` to swap login/public emails.
  See `import-staging/README.md` for the full workflow.
- **Reconcile backfilled tuition enrollments.** Migration
  `payments.0006_seed_initial_tuition_period` seeded `TuitionEnrollment`
  rows from the old `tuition_paying=true` guess on every imported member.
  Reconcile those per-year statuses against the treasurer's dues ledger
  before opening fall registration — otherwise REG-4 ("covered by tuition")
  fires for non-payers. This is a treasurer data task (admin or
  `/treasurer/`), not a code change.
- **`is_faculty=false` on every imported member.** Flip for seminar
  instructors so they can edit events (PROG-7) and mint pricing codes
  (REG-17).
- **Manual name fixes.** A handful of imported names need admin polish:
  "María Líza Ahearne" (split as first=María, last=Líza Ahearne — Líza is a
  given name), "Carlos Alberto Jimenez" / "Hannah Patricia Bennett" (middle
  names landed in last_name). The splitter handles particle-laden compound
  surnames (de la Torre, Bou Ali, Patsalides Hofmann) correctly; pure-middle
  cases require manual edits.
- **Set the actual Zoom link** in `Event.access_info` for the Working with
  Masochism event (currently a placeholder).
- **SES production access — GRANTED 2026-06-03.** The account is **out of the
  sandbox** (`ProductionAccessEnabled: true`, `MaxSendRate: 14`,
  `Max24HourSend: 50000`). SES now delivers to any recipient — the
  "verified-identities only" containment is gone, so the member-facing timers
  must stay disabled until launch is intended (below). See `ses-status` memory.
- **Re-enable member-facing notification timers at launch.** On 2026-06-01
  the three member-facing host timers were disabled
  (`sudo systemctl disable --now lsp-dues-cron.timer
  lsp-registration-reminders.timer lsp-parletre-digests.timer`) because the
  dues cron's first real Monday run emailed reminders (only the sandbox
  contained it — see above). `lsp-parletre-purge.timer` stays on. At launch:
  `sudo systemctl enable --now lsp-dues-cron.timer
  lsp-registration-reminders.timer lsp-parletre-digests.timer`. Note these
  timers live only on the host, not the repo (see `host-cron-timers` memory).
  **New at launch:** add a daily host timer running
  `manage.py send_notification_digests` (the cross-category notification
  digest — daily/weekly per member preference). Member-facing, so keep it off
  until launch like the others.
- **Reminder send rate-limiting — DONE.** `payments.sending.ThrottledSender`
  paces the batch reminder jobs to `EMAIL_MAX_SEND_RATE` (msgs/sec, default
  1.0 — sandbox-safe; raise via `DJANGO_EMAIL_MAX_SEND_RATE` once out of the
  sandbox to match the SES `MaxSendRate`) and retries transient `454`
  throttling with backoff. Wired into `send_dues_reminders`,
  `send_tuition_reminders`, and `send_registration_reminders`. **Action at
  launch:** set `DJANGO_EMAIL_MAX_SEND_RATE` in the host `.env` to the SES
  production send rate so an ~80-member batch isn't paced at 1/s unnecessarily.
- **Open login-email change to all members at launch** — set
  `DJANGO_EMAIL_CHANGE_PUBLIC=true` in the host `.env` (currently gated to
  `DJANGO_EMAIL_CHANGE_ALLOWLIST`, default rico's address).
- **Turn on admin 2FA enforcement at launch** — set
  `DJANGO_TWO_FACTOR_ENFORCED=true` in the host `.env`. The TOTP flows are
  built and enrollment is live, but enforcement ships OFF so current testers
  aren't forced through it. Flipping it requires every admin to enroll an
  authenticator on next request (recovery codes / deleting the `TOTPDevice`
  row are the lockout escape hatches). See `email-auth-2fa` memory.
- **Stripe credentials cutover** from rico's business account to the LSP's
  (Garrett's) once that account is ready.
- **SES bounce/complaint handling (someday-soon, post-launch hardening).** Now
  that SES is out of the sandbox and sends to real members, add a configuration
  set with an SNS event destination for `Bounce` + `Complaint` (also gives the
  per-message logging we currently lack). Subscribe an endpoint so hard bounces /
  complaints are visible and can suppress/flag the member address. Not urgent —
  SES's account-level suppression list is on by default and the audience is ~80
  curated addresses — but expected of a production sender. See
  `ses-bounce-complaint-handling` memory.

## Visual identity (deferred to Phase 2)

The directory page is intentionally the only page with real visual polish so
far (serif headings, neutral palette, photo card grid). Everything else is
the minimal default style. Designing a coherent visual system makes sense
*together with* the Phase 2 pages (PUB-1 about, PUB-2 faculty profiles,
CART-1/2/3 cartels, MEM-1/2/3 members-only area) rather than ahead of them —
those pages will shape what the design needs to do. Until then, the
directory's aesthetic can serve as the working seed.

## Manual-override workflow (staff, REG-14)

The design principle is *space for the singular* (principle 4.1) — every
automated path has a staff alternative through the Django admin.

| Need | Admin path |
|---|---|
| **Comp a registration** (no payment, full access) | Registration list → select rows → action *Comp selected registrations* → status flips to COMPED, comp note added to `staff_notes`, confirmation email sent with access info. Only works for `awaiting_payment` rows. |
| **Record an offline payment** (cash, check, alt arrangement) | Create a `Payment` (type=REGISTRATION/DUES/DONATION, method=OFFLINE, status=PENDING, registration optional, notes documenting the arrangement). Then select the row → action *Apply payment success* — runs the same side-effect chain as the Stripe webhook: marks SUCCEEDED, flips Registration to PAID, generates Receipt, sends emails. Idempotent. |
| **Adjust a quoted amount** | Edit `Registration.quoted_amount` directly in admin. No side-effects fire; staff is on the hook for any related downstream emails/refunds. |
| **Issue a refund / cancel** | For paid registrations, use the public "Cancel registration" button on the confirmation page (self-service Stripe refund). For staff-only flows, mark Registration status REFUNDED in admin and process the refund in Stripe Dashboard manually. |

All admin actions log their effect to `staff_notes` (where applicable) so
the override trail is auditable.

## Deploying changes

Push to `main` and `.github/workflows/deploy.yml` will run the test suite,
then trigger `~/bin/deploy.sh` on the EC2 host via `aws ssm send-command`.
That host script does `git pull && docker compose up -d --build`; migrations
and `collectstatic` run automatically in the container's startup CMD.

SSH into the host with `ssh lsp` (alias resolves to `ec2-user@54.188.243.116`
via the system `~/.ssh/config`). `.env` lives only on the host (`~/lsp-website/.env`,
mode 600) — it's `.gitignore`'d and `.dockerignore`'d. Adding a new required
env var means updating that file on the host before deploying.

For a manual deploy without GHA: `gh workflow run Deploy --repo ricopicone/lsp-website`,
or `ssh lsp '~/bin/deploy.sh'`.

## Task tracking

The eight Phase 1 milestones and broader project context live in the "LSP
Management" project of the web coordinator's project-management app, reached
through an MCP "projects connector" (tasks #213–#220). That connector is
configured in the Cowork environment used for planning; add it to this Claude
Code session's MCP config if you want to update those tasks from here. In Codex,
the equivalent remote MCP server is `projects-direct` in `~/.codex/config.toml`;
with a static `Authorization` header, do not also set `bearer_token_env_var`.
