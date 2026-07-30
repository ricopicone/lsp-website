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
