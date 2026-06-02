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
  live (SES still in sandbox pending production-access approval).
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
npm install                              # one-time: install Tailwind + DaisyUI
npm run watch:css                        # dev: rebuild static/css/site.css on save
npm run build:css                        # one-shot minified build
```

The CSS pipeline (Tailwind v4 + DaisyUI v5) compiles `static/css/input.css`
to `static/css/site.css`. The output is `.gitignore`'d — rebuild before
running the dev server, or run `npm run watch:css` in a second terminal.
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
  `workgroups-architecture` memory.
- **Cartels** (`cartels`, CART-1/2/3) — built on the Workgroup layer.
- **Directory** (`/directory/`), **Find an Analyst** map, member
  self-service **profile editor** (`/accounts/profile/`), **works**
  showcase (`/works/`), and **documents** (`/documents/`) — all live.

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
- **SES production access — awaiting AWS re-review (still sandboxed).** The
  account is **still in the sandbox** (`ProductionAccessEnabled: false`).
  `aws sesv2 get-account` shows `ReviewDetails.Status: DENIED`, but that
  reflects AWS's *automated first-pass* (auto-deny + request more info), not
  a final verdict: the support case 178015607900328 status is "Customer
  action completed" — AWS asked for detail on 2026-05-30, Rico replied the
  same day with a full transactional use-case, and it's now in AWS's queue.
  Monitor `ProductionAccessEnabled` (flips to `true` when granted); nudge the
  case if AWS is silent for a few days. **Do not resubmit.** Until granted,
  SES only delivers to *verified identities*. `dr@ricopic.one` and the
  `lacanschool.org` domain are already verified, so to test
  login-email-change end-to-end now, verify a *second* address you control
  and change `dr@ricopic.one` to it. See `ses-status` memory.
- **Re-enable member-facing notification timers at launch.** On 2026-06-01
  the three member-facing host timers were disabled
  (`sudo systemctl disable --now lsp-dues-cron.timer
  lsp-registration-reminders.timer lsp-parletre-digests.timer`) because the
  dues cron's first real Monday run emailed reminders (only the sandbox
  contained it — see above). `lsp-parletre-purge.timer` stays on. At launch:
  `sudo systemctl enable --now lsp-dues-cron.timer
  lsp-registration-reminders.timer lsp-parletre-digests.timer`. Note these
  timers live only on the host, not the repo (see `host-cron-timers` memory).
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
- **Stripe credentials cutover** from rico's business account to the LSP's
  (Garrett's) once that account is ready.

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
Code session's MCP config if you want to update those tasks from here.
