# Importing missing Stripe payments (cutover runbook)

When payments are taken **outside** the new site's own Checkout — the old Wix
site, Stripe Payment Links, invoices, or the treasurer keying a card by hand —
the site never records a `Payment` for them, so they're missing from the
directory, treasurer dashboard, and receipts. `manage.py import_stripe_payments`
backfills them from Stripe.

This is the tool for the **cutover**: after the old site stops taking payments,
run it once (or a few times during the transition) to pull in everything the new
site missed.

## Key facts

- **Same account → no special key needed.** The old site and the new site share
  one live Stripe account, so the site's own `STRIPE_SECRET_KEY` can read the
  old-site charges. Pass `--use-settings-key`. `STRIPE_IMPORT_KEY` (a restricted
  read-only key) is only needed to read a *different* account.
- **Dry-run by default.** Nothing is written unless you add `--commit`. Always
  dry-run first and read the plan.
- **Idempotent.** Every touched row carries a `[stripe-import:<charge_id>]` tag;
  re-runs skip tagged charges. Safe to run repeatedly.
- **No double-counting.** Charges the new site created at Checkout are
  *reconciled* (matched by payment-intent / checkout-session / metadata), not
  duplicated; charges that overlap a treasurer-ledger import (same member +
  amount within a few days, or a dues charge for an academic year already on
  record) are flagged as likely duplicates and skipped.
- **Provenance.** Confident new rows are `source=IMPORTED`; provisional guesses
  from `--sweep-unknown` are `source=ASSUMED` — both surface in the treasurer's
  reconcile view.

## Procedure (production)

Run inside the live web container. Blue-green means the active service is either
`web_blue` or `web_green` — check first.

```
ssh lsp
```

```
cd ~/lsp-website && docker compose ps | grep web
```

Use the running service name below (shown as `<web>`). **Dry-run first:**

```
docker compose exec -T <web> python manage.py import_stripe_payments --use-settings-key --since 2026-01-01
```

Read the report buckets:

- **create (member matched)** — new payments that will be recorded, member linked.
- **create (UNMATCHED)** — recorded with `user=null`, flagged in notes; link the
  member later in admin.
- **reconcile / reconcile_flag** — an existing site payment; `reconcile_flag`
  means it's still pending/failed, so complete it via the admin *Apply payment
  success* action (don't rely on the importer to flip it).
- **skipped: already imported / likely ledger duplicate / not paid** — correctly
  left alone.
- **skipped: type unknown** — old-site charges whose type (dues / tuition /
  registration / donation) couldn't be inferred (Wix charges often lack
  metadata). Handle these next.

### Handling unknown-type charges

Inspect them:

```
docker compose exec -T <web> python manage.py import_stripe_payments --use-settings-key --since 2026-01-01 --dump-unknown
```

Then pick one:

- `--sweep-unknown` — provisionally type the leftovers as `source=ASSUMED`
  (tuition for in-training members, registration for those who've finished
  tuition), tagged *"confirm via survey"*, and **skip charges under $25**
  (`--sweep-min`, default 25 — ignores card-test noise). This is the "import
  them all, let the treasurer reconcile" path.
- `--only-types dues,tuition` — record only certain types now, hold the rest.
- `--default-type donation` — type every remaining unknown as one type.

### Commit

Once the dry-run looks right, add `--commit`:

```
docker compose exec -T <web> python manage.py import_stripe_payments --use-settings-key --since 2026-01-01 --sweep-unknown --commit
```

**Verify** by re-running the plain dry-run — it should report
`New money to record: $0.00` and everything as *already imported*.

## After importing

- **Treasurer reconciles** the `source=ASSUMED` rows (confirm/reclassify type)
  and links any `create_unmatched` rows to members. These show up in the
  treasurer views and admin (filter Payment by `source`).
- Watch specifically for large sweeps mis-typed as tuition (e.g. donations) —
  the sweep defaults unknowns to tuition.

## Gotchas

- **`Stripe fetch failed: get`** — this was a stripe-python 15.x regression:
  `_fetch` called dict-style `.get()` on `checkout.Session` SDK objects, which
  no longer expose it. Fixed 2026-07-13 via `_session_payment_intent_id`
  (getattr-based). If it recurs after an SDK bump, look for other `.get()` calls
  on Stripe objects in `_fetch` and switch them to `getattr` / the `_g` helper.
- **Window** — `--since` bounds the fetch. The importer's history was already
  swept in an earlier run, so for ongoing cutover you only need a window
  covering "since the last run". Widen (or drop `--since`) to re-check
  everything; tagged rows just skip.
