# Resuming task #443

**Task:** Ledger follow-ups from task #439 (post-ship polish)

## Description
Deferred items from the unified-ledger / member-Account-v2 build (all reviewed-and-triaged, none urgent):

**Code follow-ups**
- Add an ACCOUNT_UPDATES notification category (+CATEGORY_META migration) for history-submission decisions; currently reuses REGISTRATION_STATUS ("Registration updates" preference label is misleading).
- Treasurer surface for "member-changed payments in the last N days" — members now have full parity (incl. donation flips, which can raise tuition_years_covered and self-clear the promotion gate); changes are audit-visible in provenance hovers but passive.
- Batch `tuition_decision_exempt` in the Overview attention loop (calls member_account per in-training member; fine at ~80, batch via accounts_overview if roster grows). Fold show_money_tab's extra Payment.exists() into the same acct call.
- Negative running balances render "$-40.00" (usd filter sign placement) — treasurer + member statements.
- payments/ledger.py: expose per-line covered amounts from member_account so tuition_clearance stops replaying the sweep inline.
- `_counts()` predicate dedup (Python vs DB-level filter in accounts_overview/audit).
- End-to-end wiring tests for comp/cancel/refund charge hooks; ProfileInline formset gate test.
- Update the Tuition Assistance Document content (stale "My LSP Tuition page" / ?tab=tuition wording — works via fallback, reads stale).

**Launch-coupled (already on launch checklist, listed for completeness)**
- Survey↔ledger reconciliation before SURVEY_ENABLED (survey-created dues payments mint no charges; survey PAID_IN_FULL enrollments mint charges without payments).
- Populate Profile.year_joined (survey) before ever minting pre-2024 dues years.

**Treasurer data work (tools all live: Assign, Re-categorize+settle, Split+settle, submissions queue)**
- Continue the cleanup pass: verify/waive assumed 24-25/25-26 dues (Accounts→Owing), Matt Lovett's likely-wrong 25-26 Skipping, mis-typed tuition payments (Garcia $5.85k, Tod $2.2k, Sheila; Chamberlin deduped to honest $1.2k credit), more ledger-vs-Stripe dedups as found (process: verify date/amount/source/intent → annotate kept Stripe row → atomically delete imported duplicates).

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

- **unified-member-ledger-design** (status) — Task #439 LIVE on prod (deployed + backfilled 2026-07-15): unified per-member ledger, 7-tab treasurer admin; --dues-from 2024-09-01 (year_joined mostly null made earlier minting unsafe); treasurer cleanup pass is the open item
- **prod-host-access-ssm** (reference) — When ssh lsp is unresponsive, run prod commands via AWS SSM (same channel as deploy); instance i-070b087afa041f233
- **treasurer-payments-rework-2026-07** (status) — Big treasurer/payments-data cleanup + UI rework shipped Jul 13-14 2026 (tasks #435/#437); interface simplification is the next planned step
- **tuition-cumulative-coverage-model** (architecture) — Tuition = cumulative ledger (total paid vs obligation), NOT per-payment-to-year allocation; obligation capped at 4 years; per-year status = oldest-first coverage
- **stripe-missing-payment-import** (reference) — Import off-site (old Wix) Stripe payments via manage.py import_stripe_payments --use-settings-key; same account so no separate key; runbook in docs/stripe-payment-import.md
- **board-officer-titles** (convention) — Board Chair/Co-chair = President/Vice President: a display relabel (role_label) AND a synced governance record (Board roster is source of truth; syncs President/VP StaffRole + MoA leadership)
- **document-inline-html-body** (architecture) — documents.Document now supports inline-HTML bodies (markdown, file optional) with a {{ annual_tuition }} token; used to de-PDF the Tuition Assistance doc (task #427)
- **ci-test-suite-parallelized** (decision) — Task #426: CI/deploy time is ~all pytest; parallelized with pytest-xdist -n auto (4-core public runner). --no-migrations is NOT viable.
- **worktree-vs-main-path-trap** (gotcha) — Sessions run in a .claude-worktrees/<name> worktree; subagents often report MAIN-repo absolute paths — edit the worktree path or edits land in main
- **rendered-markdown-docs-gotchas** (gotcha) — In-repo markdown docs (core/docs/*.md, rendered via render_doc + shown in admin Help tabs): a +/-/* starting a wrapped line inside a list item silently becomes a nested bullet
- **control-analyses-accounting** (architecture) — Task #415 SHIPPED + deployed: structured control-analysis requirement (clinical 2 / academic 3), 4-year/2-year sub-bars, School-analyst dropdown, external-analyst Meeting-of-Analysts approval
- **formation-tab-doc-links** (architecture) — My LSP > Formation tab shows in-training members their track's formation-guidelines doc, configured via FormationSettings FKs
- **public-payments-gateway** (architecture) — /payments/ is now public: anon visitors get a gateway (sign in or donate anonymously), payments_index no longer @login_required (task #414)
- **daisyui-menu-dropdown-overflow** (gotcha) — DaisyUI v5 .menu dropdowns need max-height + overflow-y-auto + flex-nowrap or they overflow off-screen on mobile (task #413)
- **personas-off-public-rosters** (gotcha) — Training-sandbox personas must be filtered off public rosters; Workgroup.active_members() now excludes them (was leaking "Persona Board Chair")
- **formation-two-tracks-not-three** (glossary) — LSP formation has TWO tracks — Clinical and Scholar (no separate "Research" track); referrals coordinated by the Referral Coordinator, not rotating analysts
- **gated-page-anon-redirect-not-404** (convention) — Gated GET pages redirect anonymous users to login with ?next= (only 404 for signed-in non-members) — use the shared core.access.gate_or_login(request) helper
- **cartel-formation-forming-first** (architecture) — Cartel formation is forming-first: members gather first, PC registration is the final step (task #392, SHIPPED + LIVE)
- **profile-geocode-on-save** (gotcha) — Profile.location changes re-geocode via Profile.save() staling + geocode_after_edit on interactive edits (task #391); geocode_profiles skips rows that already have coords
- **parletre-social-disabled** (status) — Task #360: Parlêtre school-wide social (Lounge/Welcome/Commons/Gaze/Purloined Letters) + private chats hidden from EVERYONE (incl. staff) via two flags (default OFF prod, ON dev/test), reversibly. Advocacy reminders #383/#384.
- **header-logo-crest** (decision) — Task #386: header logo shown as a paper-white circular "seal" that overflows below the header; disc stays light in both themes
- **website-review-action-items** (status) — Task #345: action items from the Annie Rogers/Diana Cuello/Garrett website review, exploded into subtasks #346–#379; being implemented on branch nimble-harbor. Key decisions: Classic default, em-dash→comma site copy, Suggest box dropped, Pa
- **em-dash-prose-style** (convention) — Style rule: UNSPACED em dashes (word—word) in docs, emails, chat. EXCEPTION (2026-07-06): member-facing site copy uses commas instead of em dashes, per Annie/Diana + Rico
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
_Manage your context as you work — `project_slug="lsp-management"`, `task_id=443`:_
- **Briefing** — before you pause/wrap up, `write_task_briefing(…)`: a concise “where things stand / next steps” so the next session resumes cleanly.
- **Task** — `set_task_next_action`, `edit_task`, `set_task_block`/`clear_task_block`, `complete_task` (or the dashboard’s **Done**).
- **Project memory** — when you learn something durable & project-wide (a convention, decision, gotcha), `add_project_memory` / `update_project_memory` so every future session across the project inherits it.
