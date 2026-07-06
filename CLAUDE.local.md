# Resuming task #345

**Task:** Meeting Action Items

## Description
From email: Meeting Action Items
(from LSP Website)

- Rico's own outgoing meeting-action-item summary; the concrete items are captured in the shared Google Doc and tracked elsewhere in the thread.

## Project memory
_Durable, shared context for this project. Read a full entry with `get_project_memory(name=…)`._

### launch-checklist (status)
Things deliberately gated OFF until launch is intended (set in the host `.env` / systemd on the EC2 box):

- **Re-enable member-facing cron timers** — `lsp-dues-cron`, `lsp-registration-reminders`, `lsp-parletre-digests` (disabled 2026-06-01 so reminders don't email real members early; purge timer stays on). **Add** at launch: a daily `send_notification_digests` timer; a daily `process_referrals` timer; a frequent (~5 min) `send_meeting_reminders` timer; a daily `send_availability_reminders` timer (task #272 — yearly analyst-availability review, self-guards once/AY, only fires when AvailabilitySettings.reminder_mode=Automatic); and **NEW (task #272): a weekly `send_interview_reminders` timer** — reminds admission interviewers with outstanding reports (only those agreed-but-not-reported, >7 days since last reminder; to the analyst only). Member-facing → keep off until launch.
- **Admin 2FA enforcement** — `DJANGO_TWO_FACTOR_ENFORCED=true`.
- **Public login-email change** — `DJANGO_EMAIL_CHANGE_PUBLIC=true` (currently allowlisted to rico).
- **SES send rate** — `DJANGO_EMAIL_MAX_SEND_RATE=14`.
- **Stripe live cutover** — rico's test account → LSP's (Garrett's) live account; roll the import key, `STRIPE_LIVE_ONLY` guard already in prod.
- **Feature flags** — `DJANGO_SUGGESTIONS_ENABLED`, `SURVEY_ENABLED`. (`DJANGO_DAILY_ENABLED`/video is ON in prod.)

Data tasks before opening registration: reconcile backfilled tuition enrollments, flip `is_faculty` for seminar instructors, un-mask 19 Google-Group members, set the real Zoom link on the Masochism event.

Note: referral workflow + analyst-availability feature + admissions-coordinator workflow are all LIVE now — only their member-facing timers (above) wait for launch. Admissions interviewer-invitation defaults to review-first (coordinator clicks Invite); set AdmissionsSettings.invitation_mode=Automatic to auto-invite on submit.

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

- **admissions-interface-ownership** (architecture) — Applications Coordinator owns the application admin (full per-applicant page); Meeting of Analysts is read-only; coordinator records the Meeting's accept/reject decision
- **admin-training-sandbox** (architecture) — Per-trainee persona sandbox (email redirected to the trainee) + guided in-app walkthroughs for training admins on the workflows without emailing real members (task #272)
- **applications-coordinator-admissions** (architecture) — Applications Coordinator is a Meeting-of-Analysts workgroup role that facilitates admissions (console at /admin-tools/applications/); SHIPPED + LIVE (task #272)
- **analyst-availability-feature** (architecture) — Task #272 SHIPPED + LIVE: analyst-availability woven into the directory (new `availability` app); all phases + review refinements deployed; 2026-2027 data + per-analyst notes imported on prod
- **event-change-review-loop** (architecture) — Approved-event content edits (title/desc/readings/fee) route through a certify-or-submit dialog; EventChangeRequest is the audit row; PC queue on the program-admin Changes tab. SHIPPED to main 2026-06-22.
- **program-archive-and-content-migration** (status) — Task #259: program archive (member-gated past-year PDFs) + old-Wix content migration mostly complete; map in docs/content-migration-map.md
- **directory-badge-colors** (convention) — Directory profile badges: Faculty=accent, board-appointee StaffRole=secondary (LSP Staff excluded; deduped vs committee officer), committee=primary
- **self-hosted-fonts** (decision) — Web fonts are bundled/self-hosted (static/fonts/), NOT loaded from Google Fonts CDN — done to kill the FOUT/reflow on page load (task #270)
- **email-from-names** (convention) — All mail shows a friendly From: DEFAULT_FROM_EMAIL is wrapped with EMAIL_FROM_NAME ("Lacanian School of Psychoanalysis"). Per-type senders use core.email.school_from(name) — e.g. referral mail is "LSP Referral Coordinator". DEFAULT_FROM_ADD
- **works-video** (architecture) — Works supports member video upload (direct-to-S3 presigned POST) + gated streaming (private S3 presigned range URLs, no transcoding). Per-file cap + on/off in the Web Developer admin. nginx 1100M kept for the no-JS fallback.
- **formation-url-collision** (gotcha) — /formation/ belongs to the member-facing admissions formation hub (with /formation/demande/ etc.). The task #259 public "Formation" content page was moved to /about/formation/ to stop it shadowing the hub. Don't move it back.
- **pushed-is-not-deployed** (gotcha) — Deploy only happens if the full CI test suite passes — a single failing test silently aborts the deploy, so a successful push to main does NOT mean prod updated. Verify the Deploy run goes green.
- **tailwind-classes-set-in-python** (gotcha) — Tailwind v4 scans templates only — CSS classes set in Python (form widget attrs) must also appear in some .html or they're dropped from the prod build
- **site-theme-modern-vs-classic** (decision) — Task #259: the old-site artwork/serif look is now an opt-in "wix"/Classic site-theme; default is Modern. Cookie-driven, footer switch.
- **old-site-artwork-and-style** (decision) — Task #259: section-landing artwork heroes + Playfair/Cinzel fonts + tuned silk palette; artwork gated on copyright (multiple artists, ../wix-files)
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
_Manage your context as you work — `project_slug="lsp-management"`, `task_id=345`:_
- **Briefing** — before you pause/wrap up, `write_task_briefing(…)`: a concise “where things stand / next steps” so the next session resumes cleanly.
- **Task** — `set_task_next_action`, `edit_task`, `set_task_block`/`clear_task_block`, `complete_task` (or the dashboard’s **Done**).
- **Project memory** — when you learn something durable & project-wide (a convention, decision, gotcha), `add_project_memory` / `update_project_memory` so every future session across the project inherits it.
