# Treasurer ledger cleanup — open worklist (task #443)

Snapshot taken 2026-07-20 against prod (`d126b37`) via a read-only survey.
This is the treasurer's working list for the reconciliation items that need
**Stripe-dashboard verification** or a **member-intent / standing judgment** —
i.e. the things a code session should *not* decide unilaterally on real money.

**Dedup process (unchanged):** verify date / amount / source / intent →
annotate the kept row → atomically delete the imported duplicate (SSM shell or
Django admin, deliberately *not* the treasurer UI). A distinct Stripe `ch_…`
id means it is a **distinct real charge** — not a duplicate — so most
"provisional" rows are genuine money, not double-counts.

---

## Done in this pass

- **Matt Lovett** (`matthew.t.lovett@gmail.com`) — AY2025-26 tuition was seeded
  `Skipping` (`src=assumed`), but he paid **$2,500 on 2025-07-16 = the exact
  25-26 rate**. Set to **Committed** (mints tuition charge C#387 $2,500, tp1).
  Balance moved `-$1,600 credit → +$900 owing` — the accurate cumulative
  picture (he is $1,000 short across four real tuition years, offset by a small
  dues over-credit). Enrollment note records the reason. *Reversible: set 25-26
  back to Skipping to drop the charge.*
- **Garcia** (`drgarcia@mendcenter.org`) — already clean. 4× $2,000 tuition on
  2022-07-11 (distinct `ch_…`) matched by 4 tuition charges; a prior session
  void'd the wrong C#382 and hand-built C#381/383/384. His "owes $150" is a
  **real** unpaid 25-26 dues balance, not an error. (The audit's "$4k vs $8k"
  is only the retired #437 formula.)
- **Chamberlin** (`christopher.e.chamberlin@gmail.com`) — already deduped
  2026-07-16 (see the note on P#223). The remaining **$1,200 credit is the
  confirmed-honest one** (provisional P#771). No action.

---

## Bucket A — "No payer" unallocated Stripe tuition (biggest item)

~**dozens of small recurring Stripe tuition charges** ($25–$500, mostly
$40/$60, 2025-09 → 2026-07) that imported with **no linked member**
(`source=assumed`, `user=NULL`). These are the bulk of the **196 provisional
rows / $48,147** and dominate the Reconcile → **No payer** tab.

- **Action:** assign each to its member (Reconcile → No payer → **Assign**),
  which re-types + links in one step. The recurring cadence + amounts should
  map to specific members' monthly tuition plans once cross-checked against
  Stripe customer/email on each charge.
- **Why not automated:** the payer identity lives on the Stripe charge
  (customer/email/description), not in our DB — needs the dashboard.

Representative rows (see the No-payer tab for the full list): P#618/617/616/615
($500 ea, 2025-09), P#612–P#548 (the $40–$320 monthly stream), P#807/800/799/794
(2026-06/07).

---

## Bucket B — Provisional rows on linked accounts ("confirm via survey")

`source=assumed` Stripe rows the import couldn't classify, already linked to a
member and tagged `(provisional — confirm via survey)`. Each needs a
**real-or-dup** decision against Stripe. Distinct `ch_…` ⇒ keep as real; only
delete if Stripe shows the *same* charge already recorded under another row.

| Member | Rows to confirm | Question |
|---|---|---|
| Tod Edgerton | P#621 ($625 "registration", 2025-07-31); P#553 ($1,250 "registration", 2026-04-09) | Same money as tz tuition #80 ($650, 07-31) / #81 ($625) installments, or distinct? Amounts differ ($625 vs $650) → likely distinct real seminar fees. |
| Casey Butcher | P#763 ($500, 2022-08-31); P#683 ($1,000, 2024-07-03) | Tuition installments (keep) vs seminar/dup? |
| Barbara Freeman | P#790/P#781 ($1,000 ea, 2021); P#680 ($480, 2024-07) | Confirm tuition intent. |
| Ayelet Amittay | P#788 ($500), P#780 ($250), P#733 ($500) | Confirm tuition intent. |
| Sand Jianglan | P#764 ($500), P#684 ($500) "registration" | Seminar fees — mint settlement charges, or keep as credit? |
| Barri Belnap | P#681 ($25), P#666 ($500), P#597 ($500) "registration" | Seminar fees — settle vs credit. |

---

## Bucket C — Accounts in credit (31 accounts, $21,544 total)

Overpaid balances. Some are **genuine** (real prepayment / extra donation-like
tuition), some are **phantom** (a provisional row from Bucket B, or a mis-type).
Triage each: if every payment is a distinct real Stripe charge, the credit is
real; if a provisional row is inflating it, resolve via Bucket B.

Largest first: Caroline Barensfeld $2,500 · Casey Butcher $2,500 · Barbara
Freeman $2,480 · Tod Edgerton $2,200 · Chamberlin $1,200 *(confirmed honest)* ·
Ayelet $1,150 · Barri Belnap $1,025 · Sand Jianglan $1,000 · Garret Barnwell
$940 · Carl Waitz $810 · … (tail of $10–$700). `Sheila@yorku.ca` $500 was named
in the task — 4 tuition years covered, $500 over; confirm whether that $500 is a
real overpay or a mis-typed row.

*(Barensfeld/Butcher $2,500: both have full tuition + a 2025-26 $2,500 tuition
payment but the 25-26 tuition **charge** hasn't minted — their enrollment/charge
state is worth a look, cf. the Matt Lovett pattern, but their credit is exactly
one 25-26 payment so it may simply be prepaid-and-awaiting-charge.)*

---

## Bucket D — Assumed 24-25 dues on the Owing list (34 accounts)

Migration-0006 seed guesses (`Charge.source=assumed`, dues, eff 2024-09-01,
$50–$150) that leave a member **owing**. For most, the member genuinely owed
24-25 dues and the charge is correct — it just needs its **provenance promoted
`assumed → verified`** (keep the debt). **Waive only** where the member did not
owe that year (joined later / non-obligated role / already paid offline).

- **Cannot be blanket-resolved from the DB** — needs each member's real 24-25
  role + standing + any offline payment.
- Full list (owes ≥ the assumed dues charge): half.outside.it $4,000 · jsettell
  $3,050 · beshara $3,000 · cbell $2,500 · insalaco $2,150 · (rico $2,000 —
  self) · shannat99 $1,880 · me33rick $1,550 · jroberts $1,180 · dianasfu
  $1,150 · … down to the $50 tail (marta, kreitzberg, lapenta, margonz, info,
  sawicki, christopherscott, winnie_bing). Charge IDs captured in the survey.

---

## Tools

Reconcile tab: **Assign** (link + re-type no-payer), **Re-categorize + settle**,
**Split + settle**, submissions queue. Per-member page: add/adjust/waive/void
charge, record offline payment, set any-year tuition status. `audit_ledger`
(read-only parity) and `audit_finances` for spot checks.
