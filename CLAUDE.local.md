# Resuming task #501

**Task:** Feature request: Payment plans for individual seminar or reading group

## Description
I think the idea would be to make a payment plan one of the code minting options for faculty/conveners of a seminar or reading group. Look into the feasibility and how clean this feature would be.

## Project memory
_Durable, shared context for this project. Read a full entry with `get_project_memory(name=…)`._

### launch-checklist (status)
**Cutover executed 2026-07-22 (task #450), including the URL cutover.**

**Flags/timers (done):** `DJANGO_EMAIL_CHANGE_PUBLIC=true`, `DJANGO_EMAIL_MAX_SEND_RATE=14`; timers enabled: registration-reminders, parletre-digests + 5 new (notification-digests 15:00 UTC, process-referrals 16:00, availability-reminders 17:00, interview-reminders Mon 17:30, meeting-reminders 5-min). `lsp-dues-cron.service` gained the missing `send_tuition_reminders` ExecStart. Stripe was already on the school's live account; final import sweep committed (6 dues payments/$800; verify $0.00). Suggestions flag moot (hard-off in production.py).

**URL cutover (done):** `https://lacanschool.org` is the canonical site. Wix-purchased domains CANNOT change nameservers (confirmed: Wix feature-request page) → DNS remains hosted at Wix; apex A + www CNAME were hand-edited in the Wix panel to the EIP (54.188.243.116). Host nginx: `lsp-canonical.conf` (apex proxy + old-Wix-path 301 map + www→apex); `app.lacanschool.org` 301s to apex EXCEPT `/payments/webhooks/` (Stripe's registered endpoint keeps proxying — POSTs don't follow redirects). One LE cert covers apex+www (exp 2026-10-20). Env: ALLOWED_HOSTS/CSRF = all three hosts; SITE_BASE_URL=https://lacanschool.org. S3 CORS (private + recordings buckets) includes the new origins. DMARC is now a real TXT (p=none, rua=website@). Gotcha: Wix's domain-unassign flow silently dropped the `app` A record (brief outage until re-added by hand).

**Reply-by-email stays on parletre.ricopic.one** — Wix's Google-Workspace MX preset blocks custom/subdomain MX records (this is WHY the test domain exists). PARLETRE_REPLY_DOMAIN was briefly flipped and reverted.

**Still deliberately HELD (Rico's decisions 2026-07-22):**
- `lsp-dues-cron.timer` disabled until the treasurer clears Accounts→Owing (assumed 24-25/25-26 dues, task #443). Enable: `systemctl enable --now lsp-dues-cron.timer`.
- `SURVEY_ENABLED` off until the survey↔ledger charge-minting gap is closed.
- `DJANGO_TWO_FACTOR_ENFORCED` off ~a few weeks so admins can log in first.

**Future: cut Wix out entirely** — "Transfer away from Wix" registrar transfer (to Route 53 Domains, ~$15/yr, 5-7 days, zero downtime). The pre-staged Route 53 hosted zone (Z07184784MROHMIJPJLF; full mirror + parletre MX/DKIM) goes live then; unlocks subdomain MX → move reply-by-email to parletre.lacanschool.org.

**Working with Masochism (special event) — DECISION 2026-07-23 (task #463):** use the **integrated in-site video meeting (Daily) NOT Zoom**. The event is format=online, daily_enabled=True on prod, access_info is empty (no Zoom link needed — the room button IS the join path). Registration was opened (status=OPEN) 2026-07-23. Speakers/faculty/PC/staff see the room + a "Join button" on the event page without registering; attendees register then get their own Join button when the event goes live (no link to send). So the old "set the real Zoom link on the Masochism event" task is DROPPED.

**Data tasks before opening registration:** reconcile backfilled tuition enrollments (#443 ongoing), flip `is_faculty` for seminar instructors, un-mask 19 Google-Group members, populate year_joined (survey) before minting pre-2024 dues years.

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

- **payment-plan-is-manual-stripe-not-autopay** (architecture) — An approved payment plan auto-charges nothing (no Klarna/BNPL/Subscriptions) — the member hand-pays each installment via Stripe Checkout, the year stays ONE annual Charge, and due-date nudges shipped 2026-08-02
- **program-committee-is-the-name** (convention) — In prose the body is the "Program Committee" — only the slug and docstrings say "programming-committee" (committees/0003 renamed it), so code is no evidence about the display name
- **faculty-guide-and-code-recipes** (architecture) — Task #495 SHIPPED 2026-08-02: /guides/faculty/ is the faculty guide (seminars AND reading groups in one); a scholarship for a non-member is an unrestricted 1-use code, and reading-group conveners now reach their own roster
- **recording-availability-intersects** (architecture) — Recording availability = six settings across two dimensions (standing × roster); listing and content INTERSECT rather than rank, so no pair is invalid and the guarantee is structural, not validated
- **officer-lead-predicate** (architecture) — Task #480 SHIPPED+LIVE: is_workgroup_lead() is the one lead primitive; the school officers lead ONLY the Board and the Meeting of Analysts, and the orphan guard deliberately stays stored-rows-only
- **active-members-vs-participants** (gotcha) — Workgroup.active_members() returns STORED membership rows only — audit a roster over participants(), or derived members (auto-role, registrants, ex-officio officers) are invisible
- **hidden-input-honeypot-is-the-weak-variant** (gotcha) — SHIPPED+LIVE (task #479, deployed 2026-07-28): type="hidden" honeypots are the variant bots skip on purpose; vowel-ratio gibberish detection flags Pittsburgh (use case transitions); referral screening HOLDS, never rejects; prod runs dist=au
- **tracker-rows-go-stale-after-shipping** (convention) — A TODO row is weak evidence work is undone — #485 and #479 both shipped and deployed while sitting TODO; verify with merge ancestry + a green deploy on that SHA or any later one
- **settings-page-saves-what-it-renders** (gotcha) — The notification settings POST loop treats a missing checkbox as OFF, so anything that changes which rows render must change the save loop too — both now go through notifications.audience.visible_categories(user)
- **queue-notifications-are-per-category-adjustable** (architecture) — Task #491 SHIPPED 2026-08-01: queue notifications were always recipient-adjustable per category; what was missing is role-sensitive DEFAULTS, now available as CategoryMeta.default_email_for
- **tuition-assistance-is-the-payment-plan** (glossary) — "Tuition assistance" and "payment plan" are ONE process, not two — an approved plan is the full annual amount over 2 or 9 installments, never a reduced total
- **deploy-script-host-is-authoritative** (gotcha) — ~/bin/deploy.sh on the EC2 host is AUTHORITATIVE and ops/deploy/deploy.sh is only a reference copy — editing the repo alone changes nothing on prod; also the deploy now bounds the BuildKit cache and prints disk state
- **messages-render-once-in-base** (convention) — SHIPPED+LIVE 2026-07-31: Django messages render once from core/_messages.html via core/base.html — never add a per-page loop, a second rendering prints every message twice (test-enforced)
- **new-modelform-field-is-required-by-default** (gotcha) — Adding a choices+default CharField to an existing ModelForm silently makes it REQUIRED, breaking every existing POST that omits it — set required=False and coerce in clean_&lt;field&gt;
- **ce-credits-on-events** (architecture) — Task #486 SHIPPED+LIVE 2026-07-30: CE credits live on the Event and are edited on the event edit form (never the Workspace Settings tab); accreditor logos come from a shared, self-growing events.CEOrganization library
- **skipping-a-covered-year-rebills-events** (architecture) — Task #485 SHIPPED+LIVE 2026-07-30: recording SKIPPING re-bills the tuition-covered registrations in that year at the regular fee (re-quote, never a bare Charge); recording a paying decision un-bills and restores access
- **new-member-blocked-until-tuition-decision** (gotcha) — A newly admitted in-training member cannot register for ANY event until they record that year's tuition decision — self-service, and EVERY option unblocks, payment-plan included
- **one-registration-gate-coverage-follows-decision** (decision) — Task #484 SHIPPED+LIVE 2026-07-30: tuition coverage follows ANY non-skipping decision (payment-plan-requested included) and the narrow special-event gate is deleted — a missing decision row is the only tuition block left
- **committee-public-is-page-not-privacy** (architecture) — Committee.public means "has a public page", NOT confidential — "Internal" is the app's word and for MoA it's the unchanged default; MoA membership is auto-derived, so directory badges must badge appointed positions only (#481)
- **advisor-pool-not-availability-gated** (decision) — Task #483 SHIPPED to main: declared availability no longer filters the advisor picker, it only labels it (three optgroups) — the picker is the only way an advisorship gets recorded
- **directory-badge-colors** (convention) — Directory profile badges: Faculty=accent, board-appointee StaffRole=secondary (LSP Staff / Registrar / Web Developer excluded; deduped vs committee officer), committee=primary
- **direct-admission-web-coordinator** (architecture) — SHIPPED+LIVE (task #476, deployed 2026-07-27): members admitted outside the site are admitted at /admin-tools/web-coordinator/admit/ (Web Coordinator, NOT the Applications Coordinator); admissions.services.admit_member() is the shared choke
- **speaker-invitation-expiry-tracks-the-event** (decision) — Speaker invitations expire the day after their event (events.speaker_invitations.invitation_expiry), not a fixed 30 days — a lapsed one is unrecoverable because password reset silently skips unusable-password accounts
- **detached-clone-loses-inherited-css** (gotcha) — A visual clone appended to document.body inherits nothing from its source element — the flourishes falling letter lost text-transform this way (task #477), so CSS-capitalized headings dropped lowercase glyphs
- **amount-only-dues-guess-swallowed-charges** (gotcha) — Stripe importer duplicate-matching: three defects fixed in #474 (circular dues guess, method-blind overlap, deceased members hidden from the matcher); full history now reconciles to $0.00 new money
- **daily-room-config-freezes-at-first-open** (architecture) — FIXED (task #475, deployed 2026-07-26): ensure_room now reconciles its full property set against the live Daily room. Comparisons must normalize — Daily stores a falsy enable_recording as the string "0". Reconciliation fires on next join, n
- **sync-charges-mints-obligations-not-payments** (glossary) — The treasurer Accounts tab's "Sync charges" button mints missing current-year DUES CHARGES (what members owe) — it never contacts Stripe and never fetches payments
- **pending-payment-is-not-money** (architecture) — A PENDING Payment only means "we sent them to Stripe" — expired checkouts now settle to the new ABANDONED status via the expired webhook + a nightly reconcile timer (task #474)
- **imported-registration-payments-have-no-charge** (gotcha) — Stripe-imported REGISTRATION payments never mint a Charge (mint_registration_charge requires a registration FK), so they read as phantom credit on the balance — the #439 backfill closed this hole for dues only
- **tuition-cumulative-coverage-model** (architecture) — Tuition + dues each accounted as their OWN bucket (category's charges vs category's payments, oldest-first, no fungibility); the single account ledger stays fungible ground truth
- **container-query-units-self-reference** (architecture) — CSS gotcha: an element with container-type can't query itself — cqw in its OWN padding/radius resolves against an ancestor container; put cqw sizing on a child
- **signup-email-verification** (architecture) — Task #471 SHIPPED+LIVE 2026-07-25: signups require email verification (inactive until confirmed, POST-gated link) + honeypot/timing/IP-cap; purge runs on lsp-signups-purge.timer daily 18:00 UTC
- **works-structured-citations** (architecture) — Task #465 SHIPPED + prod-backfilled: structured Chicago author-date citations on Work (11 fields, works/citation.py), specific type labels, random-default /works/ ordering + sort options, grid/list toggle
- **registrar-role-and-console** (decision) — SHIPPED+LIVE (task #470, deployed 2026-07-25): Registration Admin console at /admin-tools/registrations/ owned by placeholder `registrar` StaffRole (unheld, never publicly badged); PC + Web Coordinator get access via the gate predicate, not
- **formation-control-requirement-by-clinical-background** (architecture) — Formation control requirement varies by Profile.formation_background (3-state: unreviewed/clinical/academic, task #466); MoA-owned + audited; set via /admin-tools/meeting-of-analysts/backgrounds/ or advisor page, never the old bool
- **prod-host-access-ssm** (reference) — When ssh lsp is unresponsive, run prod commands via AWS SSM (same channel as deploy); instance i-070b087afa041f233
- **guest-registration-ux** (architecture) — Task #464 SHIPPED: guest-friendly registration — Event.open_to_guests (messaging-only flag), guests-welcome note on event pages, context-aware login/signup ("register for [Event]" + promoted free-account button); accounts stay required, new
- **tuition-coverage-honors-requirement-met** (decision) — REVERTED/WRONG (task #468, 2026-07-24): do NOT make seminar coverage honor 4-year-completion. Tuition covers seminars ONLY in a year the member is actively paying tuition (a covering enrollment for that AY)
- **special-event-presenters-not-faculty** (architecture) — PC-organized events (special/assembly/work day/scholarly) share the Programming Committee's workgroup, so their presenters can't be faculty — they're member_speakers, and Event.is_presenter() is what grants them the faculty view (task #463)
- **notification-url-denormalized** (gotcha) — Notification.url is stored on the row — fixing a link builder also needs a data migration to repair already-sent bell rows
- **auth-email-scanner-and-reset-gotchas** (gotcha) — Email link-scanners consume single-use links (POST-gate them); Django password reset silently skips unusable-password (imported) members
- **membership-standing-axis** (architecture) — Profile.Standing (active/on_leave/resigned/emeritus/retired/removed) is the membership axis + orthogonal Profile.deceased_on date (task #451 SHIPPED); billing keys off standing==ACTIVE; NON_MEMBER_STANDINGS={resigned,removed} gate directory
- **deleting-an-event-with-registrations** (gotcha) — To delete an Event you must first delete its Registrations: Registration.event AND Registration.price_tier are both on_delete=PROTECT
- **unified-member-ledger-design** (status) — Task #439 LIVE on prod (deployed + backfilled 2026-07-15): unified per-member ledger, 7-tab treasurer admin; --dues-from 2024-09-01 (year_joined mostly null made earlier minting unsafe); treasurer cleanup pass is the open item
- **treasurer-payments-rework-2026-07** (status) — Big treasurer/payments-data cleanup + UI rework shipped Jul 13-14 2026 (tasks #435/#437); interface simplification is the next planned step
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
_Manage your context as you work — `project_slug="lsp-management"`, `task_id=501`:_
- **Briefing** — before you pause/wrap up, `write_task_briefing(…)`: a concise “where things stand / next steps” so the next session resumes cleanly.
- **Task** — `set_task_next_action`, `edit_task`, `set_task_block`/`clear_task_block`, `complete_task` (or the dashboard’s **Done**).
- **Project memory** — when you learn something durable & project-wide (a convention, decision, gotcha), `add_project_memory` / `update_project_memory` so every future session across the project inherits it.
