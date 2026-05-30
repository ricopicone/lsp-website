# Handoff: parallel worktrees for Phase 2

This doc identifies orthogonal pieces of Phase 2 work that can run as
parallel Claude sessions in git worktrees with minimal merge friction.
Skim sections 1 and 2 to pick streams; per-stream briefs (section 4)
have everything a fresh session needs.

## 1. Current state (one screen)

**Phase 1 is on prod**: app at `https://app.lacanschool.org`, 80 members
loaded, registration/payment/dues/tuition flows working. Production
EC2 + RDS + S3, deploys via GHA → SSM. See `CLAUDE.md` for full status.

**Phase 2 in flight**, recent shipped chunks:
- `documents` app — institutional reference docs (governance, formation,
  founding texts, cartel resources, **newsletters**, reference).
  Two-axis visibility, version chains, author M2M, under-revision notice.
- `works` app — member-contributed intellectual output catalog (external
  publications, palimpsests, passages, cartel work). Multi-PDF support,
  two-axis visibility, member submission form, directory integration.
- "Members-only area" (M13) dissolved into the two apps above — see
  `handoff-vibe-card.md` for context on that pivot.
- 11 institutional docs + 10 newsletters + 1 Palimpsest seeded on prod.

**Known open issue**: the works vibe-card avatar circles don't render
visually despite correct HTML — see `docs/handoff-vibe-card.md` for
the full saga. This is its own stream (Stream A below).

**Phase 2 plan**: `../LSP-Website-Phase2-Plan.md` (sibling repo) has
the M9–M17 milestone breakdown and 10 open decisions. Skim before
starting any post-launch work.

## 2. Recommended worktree split

Four streams that touch largely disjoint file sets. Run any subset in
parallel. If you can only run two at a time, prioritize **C** (Tuition)
and **B** (Cartels) — those have real downstream value and deadlines.

| Stream | Scope | Effort | Priority | Conflict surface |
|---|---|---|---|---|
| **A** | Vibe-card avatar fix | ½ day | Low (cosmetic) | `works/templates/works/_tone_card.html` only |
| **B** | M14 Cartels app | 1–2 wk | High (unblocks CART-*, cartel-internal works) | New `cartels/` app + tiny edits in `works/`, `config/`, base.html nav |
| **C** | Tuition lifecycle refactor | 3–5 days | **Critical** (fall 2026 deadline) | `accounts/models.py` (Profile), `payments/models.py` |
| **D** | M15 Archive completion | 3–5 days | Medium (closes Wix migration) | `documents/` only, mostly new seed commands |

Avoided as parallel candidates (touch everything or are blocked):
- **Visual identity pass** — broad template work, conflicts with every
  other stream. Best done sequentially after Phase 2 pages stabilize.
- **M12.5 PC proposal workflow** — designed but deferred per memory;
  do after M14 lands so PC + cartels share the same approval shape.
- **SES production access / Stripe cutover / GG un-masking** — waiting
  on external parties (Amazon, Garrett, Workspace admin), not coding.

## 3. Coordination protocol

**Shared files — coordinate or last-merger rebases:**
- `core/templates/core/base.html` — nav, user dropdown
- `config/settings/base.py` — INSTALLED_APPS, MIDDLEWARE, settings
- `config/urls.py` — top-level URL includes
- `CLAUDE.md` — status updates

**Migrations**: each app numbers migrations sequentially per app. If
two streams both add migrations to the same app:
- Last-merged stream will need to renumber its migration and re-run.
- Try to keep migrations in your own app (e.g., Stream B keeps schema
  in `cartels/`, doesn't touch `works/` schema except for one FK
  field; Stream C keeps schema in `accounts/` and `payments/`).

**Stream B + D both might touch `documents/models.py` choices**: B
shouldn't touch documents at all (cartels is a separate app). D might
add new `Document.Category` values. If both do, last-merger rebases.

**Memory carries across sessions**: gotchas in
`~/.claude/projects/.../memory/` apply to every worktree. Notably:
- Django `{# … #}` is single-line only (4× hit, painful)
- Tailwind v4 silently drops `[N%]` / `[N/M]` arbitrary values

**Deploy ordering**: only one stream should push to `main` at a time
to avoid GHA queue contention. Coordinate merges.

## 4. Per-stream briefs

### Stream A: Vibe-card avatar fix

**Goal**: Author headshot circles render visibly in the bottom-left of
the works vibe-card (currently in DOM but visually missing).

**Owns** (will edit): `works/templates/works/_tone_card.html`,
`works/templates/works/detail.html` (cover sizing).

**Coordinates** (might touch, but rarely): nothing in shared files.

**Full context**: `docs/handoff-vibe-card.md`. That doc has the design
intent, the 10 attempts and how each failed, the user's DevTools HTML
evidence, and prioritized untested hypotheses.

**First steps**:
1. Read `docs/handoff-vibe-card.md`.
2. Verify latest commit `96d90d9` on prod with user before assuming
   it still fails (deploys can stack and confuse who saw what).
3. If still broken, ask user for the *Computed* DevTools styles on
   the avatar div + img — that resolves all open hypotheses.

**Done when**: User confirms avatars are visible in the vibe-card on
prod at `/works/palimpsest-a-voice/`.

---

### Stream B: M14 Cartels app

**Goal**: Each cartel gets a page; works can be cartel-internal
(visible only to cartel members). Unblocks the long-deferred CARTEL
kind in the works app.

**Owns**:
- New `cartels/` app (models, views, templates, admin, migrations)
- New URL routes under `/cartels/`
- New nav link in `core/templates/core/base.html` (coordinate)

**Coordinates**:
- `works/models.py` — add `Work.cartel = FK(Cartel, null=True)` and
  add `Work.Visibility.CARTEL` / `Work.PDFVisibility.CARTEL` choices.
  Single new migration. Update `Work.listing_visible_to`,
  `pdf_visible_to`, and `Work.listing_for` to handle cartel-only
  visibility (cartel members see, others don't).
- `works/forms.py` — un-hide the CARTEL kind option, expose a Cartel
  picker when kind=CARTEL.
- `works/templates/works/form.html` — add Cartel select field (shown
  conditionally on kind=CARTEL via a small JS toggle or always shown).
- `works/templates/works/detail.html` + `_card.html` — link to cartel
  page from cartel-kind works.
- `config/settings/base.py` — add `"cartels"` to LOCAL_APPS.
- `config/urls.py` — `path("cartels/", include("cartels.urls"))`.
- `core/templates/core/base.html` — add "Cartels" nav item.

**Data model sketch**:
```python
class Cartel(Model):
    name              CharField
    slug              SlugField (unique)
    description       TextField (markdown)
    plus_one          FK(User)        # the "plus-one" role per Lacan
    start_date        DateField
    end_date          DateField (null)
    public            BooleanField (default True)  # whether listed publicly

class CartelMembership(Model):
    cartel            FK(Cartel)
    user              FK(User)
    start_date / end_date
    # plus-one tracked on Cartel directly; this is the working group
```

**References**:
- `../LSP-Website-Phase2-Plan.md` for the M14 spec.
- `documents/models.py:Document` for the version-chain pattern that
  cartel periods might mirror.
- `works/models.py:Work.editable_by` for the auth helper pattern.
- Memory `program-committee-workflow` for the PC proposal workflow
  that M12.5 will likely share infrastructure with.

**First steps**:
1. Read `../LSP-Website-Phase2-Plan.md` (M14 section + open decisions).
2. Draft models. Get user sign-off on the cartel/membership shape
   before migrations.
3. Build cartels app in parallel with the small `works/` edits — the
   `works/` changes are additive (new FK + new visibility choice),
   easy to merge.

**Done when**: Cartel pages render at `/cartels/<slug>/`, members
listed, works tagged with that cartel show up there, cartel-internal
works are gated correctly, admin can manage memberships.

---

### Stream C: Tuition lifecycle refactor (critical)

**Goal**: Replace the current `Profile.tuition_paying` boolean stopgap
with a proper enrollment model that tracks 4 non-contiguous tuition
years. **Blocks correct REG-4 ("covered by tuition") pricing by fall
2026** — see memory `tuition-lifecycle`.

**Owns**:
- `accounts/models.py` — refactor `Profile.tuition_paying` semantics
- `payments/models.py` — likely already has `TuitionPeriod` and
  `TuitionEnrollment`; reconcile with the new Profile shape
- `payments/views.py` + `payments/templates/` — tuition flow
- `accounts/management/commands/` — bulk migration command for
  existing tuition_paying=true rows (reconcile with treasurer ledger)

**Coordinates**:
- `events/pricing.py:resolve_price` — the REG-4 path. Update to use
  the new enrollment lookup instead of the boolean.
- Documentation in `CLAUDE.md` — flag the change.

**Context — what's there now**:
- `Profile.tuition_paying` boolean: stopgap, true for everyone on
  initial import (a known guess that needs reconciliation per
  `CLAUDE.md`).
- `Profile.IN_TRAINING_ROLES` defines who owes tuition.
- `Profile.is_tuition_current(on_date)` already exists as the
  intended source of truth — reads from `TuitionEnrollment` rows. The
  pricing resolver hasn't been migrated to use it yet.
- `payments/models.py` already has `TuitionPeriod`, `TuitionEnrollment`,
  `TuitionInstallment` from earlier milestones.

**The work**:
1. Audit current uses of `Profile.tuition_paying` and switch them to
   `Profile.is_tuition_current(date)`.
2. Add a migration to remove the boolean field (or keep as legacy
   readonly).
3. Build a treasurer-facing import/reconciliation tool to convert
   the existing `tuition_paying=true` flags into real
   TuitionEnrollment rows for the relevant academic years.
4. Update REG-4 pricing path to use the enrollment lookup.

**References**:
- Memory `tuition-lifecycle` — full background.
- `accounts/models.py:Profile.IN_TRAINING_ROLES`,
  `is_tuition_current`, `current_tuition_enrollment`.
- `payments/models.py:TuitionEnrollment`.
- `events/pricing.py` for the REG-4 short-circuit.

**Done when**: REG-4 ("covered by tuition") correctly fires only for
users with a current-period TuitionEnrollment with
`covers_seminars=True`, validated against treasurer ledger for the
current academic year.

---

### Stream D: M15 Archive completion (Wix migration finish)

**Goal**: Migrate the remaining historical content from `wix-files/`
into the new site so the legacy Wix-side has nothing of consequence
to refer back to.

**Owns**: `documents/` only.

**Coordinates**: minimal; might add `Document.Category` values
(coordinate with Stream B if it's also adding categories — though it
shouldn't).

**Inventory of remaining content** (from `wix-files/`):
- **20+ historical program PDFs** (1994 first program, 2005-2006
  through 2024-2025). These are yearly seminar programs — snapshots
  of what was offered each academic year.
- **Palimpsests** — 2 PDFs already seeded as Works (Laura's). Future
  Palimpsest essays will be added by members via /works/add/.
- **Passages** — no PDFs in current export; might emerge later.
- **Cartel work** — 1 PDF `Cartel on Speech and Writing Final
  04302026.pdf` not yet seeded (the user can add via /works/add/
  with cartel kind once Stream B ships).
- **Member statements of teaching** (Statement of Teaching 6.14.23.pdf
  etc.) — small set, probably Documents under a new category or
  Faculty-page material (defer).

**The work**:
1. Decide: historical programs → new `Document.Category.PROGRAM_ARCHIVE`
   (or just `REFERENCE`?). Discuss with user.
2. Write `seed_program_archive` management command, similar shape to
   `seed_newsletters`. Display order = year, title = "LSP Program
   YYYY-YYYY".
3. Each PDF is institutional output (no individual author).
4. Stage PDFs locally + ship to prod via `docker compose cp` + seed
   (pattern in earlier session).

**References**:
- `documents/management/commands/seed_newsletters.py` — closest
  template for the new command.
- `documents/management/commands/seed_documents.py` — original pattern.
- `wix-files/` directory listing for available PDFs.

**Done when**: All historical programs visible at `/documents/` under
the chosen category, in chronological order, with download links.
User confirms the legacy Wix members-area content is fully migrated.

## 5. Suggested order if running one stream at a time

1. **Stream A** (vibe-card, ½ day) — gets that cosmetic bug off the
   board fast so it stops blocking eyeball feedback on other work.
2. **Stream C** (tuition, 3–5 days) — has the only real deadline
   (fall 2026 registration). Critical before fall.
3. **Stream B** (cartels, 1–2 weeks) — biggest piece, unblocks the
   CART-* and cartel-internal works features.
4. **Stream D** (archive, 3–5 days) — closes the Wix migration.

If running 2 in parallel: **C** + **B**. If 3: + **A**. If 4: + **D**.

## 6. What to look at first in any session

1. `CLAUDE.md` (always auto-loaded into context) — project orientation.
2. Memory at `~/.claude/projects/.../memory/MEMORY.md` — gotchas,
   AWS info, deploy pipeline, prior decisions.
3. `../LSP-Website-Phase2-Plan.md` — milestone breakdown + open
   decisions (sibling repo, read before architectural choices).
4. `../LSP-Website-Architecture-Phase1.md` — for the foundational
   patterns the project follows.

## 7. Deployment + testing reminders

- `uv run pytest -x -q` before pushing. Full suite is ~30s.
- `uv run ruff check <changed_dirs>` — CI runs both.
- `npm run build:css` after touching templates that introduce new
  Tailwind classes. The output is gitignored but the build runs on
  deploy via Dockerfile.
- Push to `main` triggers GHA → SSM → EC2. ~2–3 min for the rolled
  container to be live. Don't pile pushes back-to-back without
  letting a deploy land.
- Idempotent management commands are the canonical way to load prod
  data — see the `seed_*` commands for the pattern (dry-run flag,
  per-row try/except, update-or-create by slug).
