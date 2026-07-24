# Works Polish — Design (task #465)

Date: 2026-07-24
Status: approved by Rico 2026-07-24

Members are adding works and the catalog is filling in. This design covers four
polish items for the `works` app: structured citation data for external
publications, presentation improvements, ordering (random default + explicit
sort options), and a compact list view alongside the card grid — plus a curated
migration of the existing entries.

## Context (current state)

- `Work.publication_info` is a single free-form citation line; `url` and
  `publication_date` are the only other citation-ish fields.
- The detail page shows `publication_date` **only when** `publication_info` is
  empty (a bug — both should be usable together). Cards show author/year/kind
  only. The external link renders as a generic "External link →" button.
- Default ordering is `Meta.ordering = (-publication_date, -created_at)`, so
  undated works sort by recently-added. No sort UI, no pagination, grid only.

## 1. Structured citation fields (external publications)

New optional fields on `Work`, edited only when `kind == external` (the form
shows/hides the fieldset based on the Kind select; values are harmless but
unused for other kinds):

| Field | Type | Notes |
|---|---|---|
| `external_type` | choices | `article` (Journal article), `book` (Book), `chapter` (Book chapter), `edited_volume` (Edited volume), `other` (Other) |
| `container_title` | Char(255) | Journal name, or the containing book's title for a chapter |
| `publisher` | Char(255) | |
| `edition` | Char(50) | e.g. "2nd ed." |
| `volume` | Char(50) | free text — "12" |
| `issue` | Char(50) | free text — "2" |
| `pages` | Char(50) | free text — "33–58", "vii–xii" |
| `editors` | Char(255) | free text, names only ("Jane Doe and John Roe") |
| `translators` | Char(255) | free text, names only |
| `doi` | Char(255) | bare DOI ("10.1234/xyz"); rendered as an `https://doi.org/…` link. Accept a pasted full DOI URL and normalize to the bare form on clean. |
| `isbn` | Char(32) | |

`publication_info` **stays** as a legacy fallback. Form label becomes
"Citation note". Rendering rule: the formatted citation is built from the
structured fields; `publication_info` renders *after* it when both exist, or
*alone* when no structured fields are filled. No data loss either way.

### Citation renderer

New module `works/citation.py` with `format_citation(work) -> SafeString`
(and a plain-text twin for the copy button), rendering **Chicago author-date**:

- Article: `Authors. 2024. "Title." <i>Container</i> 12 (2): 33–58.` + DOI link
- Chapter: `Authors. 2024. "Title." In <i>Container</i>, edited by E, 33–58. Publisher.`
- Book: `Authors. 2024. <i>Title</i>. Edited/Translated by T. 2nd ed. Publisher.`
- Edited volume: like Book but authors read as editors ("…, eds.").
- Other / partial data: degrade gracefully — emit whatever pieces exist in
  Chicago order, skipping empty parts; never render dangling punctuation.

Author names come from the existing byline order (`WorkAuthor` +
`external_authors`), formatted Chicago-style: first author "Last, First",
subsequent "First Last", joined with ", and". Year from `publication_date`
(fall back to "n.d." only inside the Cite block, not on the header line).
All member-entered text is escaped; only our own `<i>`/link markup is safe.

## 2. Presentation

Detail page (`works/detail.html`):

- Fix the date/info bug: show the formatted source line *and* the date-derived
  year together; drop the exclusive `if`.
- Header source line: italic venue, vol/issue, pages, publisher, year —
  the formatted citation minus authors/title (those are already in the header).
- DOI/ISBN shown discreetly (DOI as a link).
- Rename "External link →" to "View at publisher" for external works
  (unchanged wording for other kinds).
- New **Cite** section (external works with any citation data): the full
  Chicago citation + a copy-to-clipboard button (plain-text form).

Cards (`_card.html`): one added line — italic container/publisher + year —
line-clamped to keep the grid tidy.

## 3. Ordering

- **Default: random every load** — `order_by("?")`. Table is small (tens of
  rows); acceptable on Postgres and SQLite.
- Sort select on `/works/` (`?sort=`), composing with the existing filters:
  - `random` (default) — shuffle
  - `year` — newest publication first, undated last
  - `added` — recently added first
  - `author` — A–Z by first LSP author's last name (subquery on
    `WorkAuthor` with `display_order` minimum), falling back to
    `external_authors` for works with no LSP author; blank-author works last
- `Meta.ordering` on `Work` is untouched — group Work tabs and other
  consumers keep their current behavior.
- No pagination (random order would break it; catalog is small).

## 4. Grid/list toggle

- Icon toggle (grid / list) next to the Sort select. `?view=list|grid` wins;
  otherwise a cookie (`works_view`, 1-year, set by the view on explicit
  toggle) remembers the choice; default grid.
- List row template (`_row.html`): authors, year, linked title, italic venue,
  kind badge, Members badge, small PDF/video markers. Citation-flavored,
  denser than cards; no cover images.

## 5. Migrating existing entries

- The legacy fallback (§1) makes deploy safe regardless of backfill timing.
- **Curated backfill, not heuristic parsing:**
  1. Pull every external Work's `title / publication_info / url /
     publication_date / external_authors` from prod (read-only).
  2. Hand-convert each to the structured fields in a reviewable JSON mapping
     file (Rico can eyeball it before applying).
  3. Idempotent `manage.py backfill_citations mapping.json [--dry-run]`
     applies it: fills **only empty** structured fields (never overwrites
     member edits), logs every change.
- Unconfidently-parseable entries stay on the legacy line; members can edit
  their own later.
- Mapping file + command live in the repo as the audit trail
  (`import-staging/` pattern for the mapping).

## Testing

- `works/citation.py`: unit tests per type (article/chapter/book/edited
  volume), partial-field combinations, punctuation edges, escaping, DOI
  normalization, legacy fallback.
- Views: sort params (each option + bogus values fall back to random), view
  toggle + cookie behavior, filters still compose.
- Form: structured fields save; kind-gated display is JS-only (no server-side
  clearing — values persist if kind changes, by design).
- `backfill_citations`: dry-run, idempotency, only-fills-empty rule.
- Migration is additive-only; existing tests stay green.
