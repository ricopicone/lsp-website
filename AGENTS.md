# Resuming task #253

**Task:** Handle outstanding suggestions queue

## Description
We have our first suggestion. Let's handle it.

## Project memory
_Durable, shared context for this project. Read a full entry with `get_project_memory(name=…)`._

### launch-checklist (status)
Things deliberately gated OFF until launch is intended (set in the host `.env` / systemd on the EC2 box):

- **Re-enable member-facing cron timers** — `lsp-dues-cron`, `lsp-registration-reminders`, `lsp-parletre-digests` (disabled 2026-06-01 so reminders don't email real members early; purge timer stays on). **Add** a daily `send_notification_digests` timer at launch, **and** a daily `process_referrals` timer (referral auto-followups when that step is set to automatic + retention redaction; safe anytime but member-facing in auto mode).
- **Admin 2FA enforcement** — `DJANGO_TWO_FACTOR_ENFORCED=true` (flows built, enforcement off so testers aren't blocked).
- **Public login-email change** — `DJANGO_EMAIL_CHANGE_PUBLIC=true` (currently allowlisted to rico).
- **SES send rate** — `DJANGO_EMAIL_MAX_SEND_RATE=14` (SES out of sandbox; default 1/s paces batches unnecessarily).
- **Stripe live cutover** — rico's test account → LSP's (Garrett's) live account; roll the import key, `STRIPE_LIVE_ONLY` guard already in prod.
- **Feature flags** — `DJANGO_SUGGESTIONS_ENABLED`, `SURVEY_ENABLED`, `DJANGO_DAILY_ENABLED` (video).

Data tasks before opening registration: reconcile backfilled tuition enrollments, flip `is_faculty` for seminar instructors, un-mask 19 Google-Group members, set the real Zoom link on the Masochism event.

Note: the referral workflow itself is LIVE now (Diana appointed 2026-06-12) — only its daily timer waits for launch.

### do-not-over-automate (decision)
The school **explicitly asked that automation not remove human discretion** (architecture §4.1, "space for the singular"). Faculty use sliding-scale and "none turned away for lack of funds" pricing; tuition-paying members are exempt from seminar fees; some faculty bill per class.

**Every automated path must keep a manual staff override** (REG-14), routed through Django admin:
- Comp a registration (Registration admin action).
- Record an offline/cash/check payment (Payment + "Apply payment success" action — same side-effects as the Stripe webhook).
- Adjust a quoted amount; issue a refund/cancel.

Admin actions log to `staff_notes` for an auditable override trail. When designing any new feature, preserve a human escape hatch.

### phase1-status (status)
Phase 1 build is task **#212** (due 2026-07-19), broken into 8 milestones (tasks #213–#220):

- **M1–M6 DONE:** scaffold/accounts/import → events/pricing → registration → Stripe payments/webhooks/receipts → dues/donations/exports → manual overrides + security review.
- **M7 TODO** (#219): production deploy + load member list + **Stephanie Swales & Derek Hook seminar dry-run**. We're already on prod, so M7 is mostly data load + dry run.
- **M8 TODO** (#220): buffer for fixes + **open fall registration**.

Reality check: the codebase runs **well ahead of these tasks** — much of Phase 2 is already built and deployed (see [[phase2-shipped]]). The milestone tasks lag the actual ship state.

### project-overview (architecture)
A custom **Django 5.2 / Python 3.10+** web app for the **Lacanian School of Psychoanalysis (LSP)**, replacing a Wix + Typeform setup. Built and maintained by Rico Picone as the school's Web Coordinator.

- **Phase 1 scope:** member accounts & roles, event registration, payments. Target: fall registration live ~mid-July 2026.
- **Live in production** at `app.lacanschool.org` on AWS.
- Repo `ricopicone/lsp-website`. Deep implementation memory lives in-repo (see [[code-memory-location]]); planning docs in [[planning-docs]].

Stack: uv deps, SQLite (dev) / Postgres-RDS (prod), Stripe hosted Checkout, Amazon SES email, Django Channels + daphne (realtime), Tailwind v4 + DaisyUI. See [[tech-stack]].

- **referral-coordinator** (status) — Referral Coordinator workflow (task #229) SHIPPED + LIVE 2026-06-12: referrals app at /admin-tools/referrals/ (tabbed UI + Help), Diana appointed, 36-clinician list imported, date-based references (26-0612), live-tested end-to-end
- **devapi-mcp-server** (architecture) — Web-developer admin: token-auth /devapi/ JSON API + stdio MCP server (task #252); first slice = Suggestions triage, built to grow
- **account-custodians** (reference) — Who holds which LSP accounts: Caroline Barensfeld = Google Workspace admin (lsp-members export); Wix = registrar for lacanschool.org; lspwixwebsite@gmail.com mystery (Typeform MFA)
- **em-dash-prose-style** (convention) — Writing-style rule (recurring correction): use UNSPACED em dashes (word—word, never word — word) in all prose written for this project — site copy, docs, emails, chat
- **code-memory-location** (reference) — Deep, code-level implementation memory lives IN the repo, not here: CLAUDE.md (project context + status log) + a 40+ entry file-based memory index (MEMORY.md) under the Claude Code project dir. This connector memory is the project-managemen
- **planning-docs** (reference) — Planning docs are loose LSP-Website-*.md files in ~/LSP-Web-Coordinator (parent of the repo): Requirements-Spec (USR-/REG-/PROG- IDs), Architecture-Phase1, Phase2-Plan (M9–M17 + 10 open decisions). Edit in place, never git-commit them
- **glossary** (glossary) — LSP/domain glossary: Parlêtre, cartel, working group, committee, seminar, formation pipeline (palimpsest/passage/traversée), Meeting of Analysts, Days of Assembly, auditor, dues vs tuition, roles
- **phase2-shipped** (status) — Much of Phase 2 already built & deployed (pulled forward): Parlêtre discussion board, Workgroups layer, document editor, Daily.co video rooms, notifications center, directory + Find-an-Analyst map, admissions pipeline, treasurer/Stripe fina
- **workgroups-layer** (architecture) — Architectural spine for group features: one shared workgroups.Workgroup (roster + auto Parlêtre channel + works/files/meetings, capability toggles) that cartels, committees, working groups, seminars, and reading groups all ATTACH. Rule: add
- **profile-and-roles** (architecture) — Custom email-login User (no username, AUTH_USER_MODEL — extend, never swap); every User auto-gets a Profile via signal; Profile.role (7 LSP roles) is the single source of truth for pricing tiers + members-only access; is_faculty and is_lsp_
- **aws-infra** (reference) — Hosting on AWS account 493980123073, region us-west-2, CLI profile `lsp`: single t4g.small EC2 (Docker compose + host nginx + Let's Encrypt), Postgres 16 on RDS, two S3 buckets (public + private/gated), SES in us-west-2. Backups + off-regio
- **deploy-pipeline** (convention) — Deploy = push to main → GitHub Actions runs tests → SSM triggers ~/bin/deploy.sh on EC2 (git pull + docker compose build). Now blue-green/zero-downtime. `.env` lives only on the host. SSH via `ssh lsp`
- **tech-stack** (architecture) — Django 5.2/Python 3.10+, uv for deps, SQLite (dev)/Postgres-RDS (prod via DATABASE_URL), Stripe hosted Checkout, Amazon SES, Django Channels+daphne (ASGI realtime), Tailwind v4 + DaisyUI v5 (build step), settings split by env

---
_Manage your context as you work — `project_slug="lsp-management"`, `task_id=253`:_
- **Briefing** — before you pause/wrap up, `write_task_briefing(…)`: a concise “where things stand / next steps” so the next session resumes cleanly.
- **Task** — `set_task_next_action`, `edit_task`, `set_task_block`/`clear_task_block`, `complete_task` (or the dashboard’s **Done**).
- **Project memory** — when you learn something durable & project-wide (a convention, decision, gotcha), `add_project_memory` / `update_project_memory` so every future session across the project inherits it.

## Session update — 2026-06-12

- The `lsp-admin` shell command is not on PATH in Codex. The repo MCP client can still be used directly with:
  `uv run --group mcp python -c 'import importlib.util, json; spec=importlib.util.spec_from_file_location("lsp_mcp_server", "mcp/lsp_mcp_server.py"); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print(json.dumps(mod.whoami(), indent=2))'`
  Import by file path because `import mcp...` collides with the installed `mcp` package.
- MCP whoami succeeded against `https://app.lacanschool.org/devapi/whoami/` as Rico Picone (`dr@ricopic.one`), roles `lsp_staff`, `web_coordinator`, `web_developer`, superuser, token label `fichte`.
- Suggestions queue had one open item: #1, “Adding a Donatation Page,” from John Kreitzberg. The donation flow already existed at `/donate/`; implementation added a logged-in account/avatar menu link labeled “Donate to LSP” and a nav regression test.
- Suggestion #1 was marked `planned`, then `done`, through the dev API. Focused verification passed: `uv run pytest core/tests.py::test_nav_staff_tools_link_visibility core/tests.py::test_account_menu_shows_donation_link payments/test_dues_donations.py` (`19 passed`, one existing Django 6.0 URLField warning).
- The Projects connector tool `_complete_task(project_slug="lsp-management", task_id=253)` failed with `400: "We couldn't connect your account. Please try again."` even though the dev API MCP token works; likely separate Projects connector auth/token, not the LSP dev API token.
