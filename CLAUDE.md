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
- Stripe (hosted Checkout) for payments and Amazon SES for email — not yet built.
- Hosting: AWS, on the `register.lacanschool.org` subdomain.

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
accounts/       custom User, Profile (incl. faculty fields), bulk import   <- built
committees/     Committee + CommitteeMembership (USR-7)                    <- M2
events/         Events, Sessions, PriceTier, PricingCode, recurrence helper <- M2
registrations/  registrations                                              <- M3
payments/       payments, receipts, Stripe                                 <- M4
core/           shared utilities, unified calendar (PROG-6)                <- M2/M3
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
- Committee memberships (Board, Program Committee, LSP Staff) live in the
  `committees` app as structured `Committee` + `CommitteeMembership` models
  (with named roles and term dates), not Django auth Groups. Memberships
  drive admin permissions.
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
- User / Profile / roles — email-login `User`, `Profile` with the seven LSP roles
  and a `tuition_paying` flag, auto-created per user, plus the admin back office.
- CSV bulk-import (`USR-3`) — `manage.py import_users path/to/file.csv`
  with `--update` and `--dry-run`. Atomic, dedupes by email case-insensitively,
  creates users with an unusable password (they set one via password reset
  once SES is wired up).
- AWS skeleton deployment — Phase 1 skeleton live at
  `https://app.lacanschool.org/admin/` on a single t4g.small EC2 (Amazon
  Linux 2023, `~/lsp-website/`) running the Django app in Docker via
  `compose.yml`, fronted by host-level nginx with a Let's Encrypt cert
  (auto-renewed via a systemd timer). Postgres 16 on RDS `lsp-db`
  (db.t4g.micro, private). Email on SES (DKIM-verified; production-access
  request pending). See `aws-infra` memory for endpoints, SG IDs, and the
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
- Dues at `/dues/` (login req, $100/year via `DUES_ANNUAL_AMOUNT`),
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

Milestones 7–8 then cover production deploy + Swales &amp; Hook dry-run
(M7 — we're already on prod, so M7 is mostly data load + dry run) and
opening fall registration (M8).

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
- **`tuition_paying=true` on every imported member is a guess.** Reconcile
  against the treasurer's dues ledger before opening fall registration —
  otherwise REG-4 ("covered by tuition") fires for non-payers.
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
- **SES production access** — request still pending Amazon approval.
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
