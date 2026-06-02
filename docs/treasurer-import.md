# Importing the treasurer's historical tuition & dues ledgers

The treasurer tracked **tuition** and **dues** in per-academic-year Excel files
with no stable identifiers — just a typed name, an amount, a date, and (for
tuition) an installment label. This document describes the one-time backfill
that loads those payments into the app's `payments` models, and how to re-run it
when next year's ledger arrives.

The tool is `manage.py import_treasurer_payments`, backed by
`payments/treasurer_import.py` (parsing + name matching). Tests:
`payments/test_treasurer_import.py`.

## What gets imported

| Source file | Dataset key | AY | Full tuition |
|---|---|---|---|
| `Tuition 24-25.xlsx` | `tuition-24-25` | 2024–25 | $2000 |
| `Treasurer 2026/Tuition 25-26.xlsx` | `tuition-25-26` | 2025–26 | $2500 |
| `Dues 24-25.xlsx` | `dues-24-25` | 2024–25 | tiers 50/100/150 |
| `Treasurer 2026/Dues 25-26.xlsx` | `dues-25-26` | 2025–26 | tiers 50/100/150 |

Each **tuition** row → one `Payment` (type=`tuition`, status=`succeeded`) linked
to a reconstructed `TuitionInstallment`, plus one `TuitionEnrollment` per
(student, year). Enrollment status is derived from the year's total vs. the
period's full tuition: `paid_in_full` if total ≥ full, else `payment_plan`.

Each **dues** row → one `Payment` (type=`dues`) attached to that year's
`DuesPeriod`. Rows tagged `DONATION` become type=`donation` with no period.

`TuitionPeriod` / `DuesPeriod` rows are created on demand (idempotent). The
period is chosen by **source file**, not payment date — tuition payments legitimately
straddle the Sept 1 academic-year boundary (e.g. a 24–25 payment dated July 2024).

> **Note:** the seminar / event / reading-group ledgers (`Seminar General 25-26`,
> `Seminar Payments 24-25`, the per-instructor files, `Cinema Lacan`,
> `Freud Reading Group`, `DOA 2026`) are **not** imported here. They map to
> `Registration` rows tied to specific `Event`s — a separate, larger effort.

## Safety properties

- **Dry-run by default.** Without `--commit` it writes nothing (atomic
  transaction rolled back) and prints a reconciliation + unmatched-names report.
- **Idempotent.** Every created `Payment` is stamped with an import tag in
  `notes` (e.g. `[tz-import:tuition-24-25#12]`). Re-runs skip already-imported
  rows, so running twice is harmless and adding next year's file only imports the new rows.
- **No side effects.** No `Receipt` rows, no emails — this is a back-office backfill.
- **High-confidence matching only.** A payer name resolves to a `User` only via:
  a verified alias (see below), exact normalized name, order-independent
  token-set, unique last-name + first-initial, or unique subset-of-roster-name
  sharing the surname. Anything ambiguous is **skipped and listed**, never
  guessed.

### The verified alias map

`ALIASES` in `payments/treasurer_import.py` maps specific raw ledger names to the
canonical roster name. Every pair was confirmed 1:1 against the live roster, so
this stays within the high-confidence bar — it is not fuzzy matching. It covers
two cases the structural rules can't safely catch on their own:

- **Roster spelling / ordering differences:** `Chan Wai Lim` → *William Chan*,
  `Wu Bing` → *Winnie Wu*, `Jiang Lan` → *Sand Jianglan*, `Shanna Carlson` →
  *Shanna Carlson de la Torre*, `Liu Ronan` → *Ruonan Liu*, etc.
- **Outright ledger typos:** `Lascano`→Lazcano, `Hofman`→Hofmann,
  `Davison`→Davidson, `Bennet`→Bennett, `Calumn Neil`→Calum Neill,
  `Chamberlain`→Chamberlin.

If a ledger name aliases to a canonical name that *isn't* uniquely in the roster,
the row is reported unmatched (with a clear reason) rather than mis-assigned —
add the member to the roster or fix the alias target. With the current map, the
2024–26 ledgers match ~99% of rows; the residual unmatched are genuine
non-members / unconfirmed identities for the treasurer to place by hand.

## Running it

The matcher needs the live member roster, so run against **production data** (or
a prod snapshot) — a fresh/empty dev DB matches nothing.

```bash
# 1. DRY-RUN first — review the reconciliation report and the unmatched list.
python manage.py import_treasurer_payments \
    --source-dir /path/to/LSP-Web-Coordinator/treasurer-files

# 2. Optionally restrict to specific datasets while iterating:
python manage.py import_treasurer_payments --source-dir ... \
    --datasets tuition-24-25 dues-25-26

# 3. When the report looks right, COMMIT:
python manage.py import_treasurer_payments --source-dir ... --commit
```

On the EC2 host the files must be copied in first (they're not in the repo), then
run inside the app container, e.g.:

```bash
scp -r "/local/path/treasurer-files" lsp:~/treasurer-files
ssh lsp 'cd ~/lsp-website && docker compose exec -T web \
    python manage.py import_treasurer_payments --source-dir /tmp/treasurer-files'
# (bind-mount or docker cp the files to the container path you point --source-dir at)
```

## Handling the unmatched list

After a dry-run, the report prints every distinct unmatched payer name per
dataset. For each, either:

1. **Fix the roster** — correct a member's name/`display_name` in the admin so
   the matcher resolves it (preferred when the ledger spelling is the correct one).
2. **Add the payment manually** — for true non-members, third-party payers, or
   names with no roster entry, create the `Payment` (and `TuitionEnrollment` /
   `TuitionInstallment` for tuition) by hand in the admin, following the
   manual-override workflow in `CLAUDE.md`.

Re-running after roster fixes is safe (idempotent) and will pick up the
newly-resolvable names.

## Adjusting for new years

Add a `Dataset(...)` entry to `DATASETS` in
`payments/management/commands/import_treasurer_payments.py` with the new file
path, AY start year, and full tuition amount, then dry-run → commit.
