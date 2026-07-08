# Cartel Formation Workflow — redesign (task #392)

**Status:** approved 2026-07-07. Reorders the existing cartel formation
machinery so a cartel forms *among members first* and Programming Committee
(PC) review moves to the **end** (registration), rather than being the front
gate. Most machinery already exists; this is a re-sequencing plus two new
data fields.

## Problem

The shipped cartel flow (CART-4) gates on the PC *first*: a member proposes a
cartel, it stays **hidden** until the PC approves it, and only then does it
become visible/joinable (`OPEN`). The school's actual cartel process is the
inverse — an initiator gathers cartelisands around a theme, the emerging
cartel meets and settles its details, and *then* it registers with the PC.

## Desired workflow (from task #392)

1. An **initiator** proposes a cartel **to other members of the school** (not
   directly to the PC) around a theme. Members can be **pre-selected**
   (direct invitation), left to an **open call**, or a **mix**.
2. As cartelisands join — or at the initiator's proposal — **any cartelisand
   can close membership**.
3. The emerging cartel **meets** to: let each member formulate a **unique
   question** (with a place to manage it as the cartel evolves); hold a
   **conversation on the symbolic position of the plus-one** before selecting
   someone for it; and **agree a fixed period** of work, **≥ 1 and ≤ 2 years**.
4. After the meeting, any member enters this information into the emerging
   cartel's settings and **assigns the plus-one** (internal or external to
   LSP).
5. Once entered, **any member can submit the cartel for registration and PC
   review** (per-member questions are recommended but not required).

## What already exists (do not rebuild)

A cartel is a `Workgroup(kind=cartel)` with a thin `Cartel` attached
(`cartels/models.py`). Reused as-is:

- **Roster + plus-one** — plus-one is `WorkgroupMembership.Role.PLUS_ONE`
  (a role, not a field); `Cartel.set_internal_plus_one` / `clear_internal_plus_one`.
- **External plus-one** — `cartels.ExternalPlusOne` (name/affiliation/bio/email +
  invite-to-signup). *(The intended external→internal conversion on signup is a
  pre-existing gap — out of scope here; note it but don't fix in this task.)*
- **Invitations** — `WorkgroupInvitation` (pre-selected members; direct-accept).
- **Open application** — `WorkgroupJoinRequest` (member-gated: any existing
  member accepts/declines).
- **Close-to-new-members** — `Cartel.closed` boolean, toggled by any active
  member (`manage` view, `set_closed`).
- **PC review** — the PC decision path (`review_queue`, `review_decide`,
  `approve`/`decline`) and the Cartel Coordinator advisory feedback path
  (`coordinator_feedback` view).
- **Edit + resubmit** — declined proposals edit-and-resubmit
  (`Cartel.resubmit` → `WorkgroupProposal.resubmit`).
- **Notification/email matrix** — `cartels/notifications.py` + `cartels/emails.py`,
  categories `CARTEL_INVITE/APPLICATION/DECISION/PROPOSAL`.
- **Duration window** — `Workgroup.start_date` / `end_date`.

## Design

### 1. State machine

A **cartel-owned** registration status drives the flow, leaving the shared
`WorkgroupProposal.Status` and `Workgroup.Lifecycle` enums undisturbed for the
other group kinds (working groups, committees, seminars, reading groups):

```
FORMING ──submit──▶ SUBMITTED ──PC approve──▶ REGISTERED
   ▲                    │
   └────PC decline──────┘   (with note; any member may revise + resubmit)
```

New field `Cartel.registration_status` (TextChoices):

- `FORMING` — initiator has proposed; the cartel is **live among members**
  from this moment (§2). Membership grows; details get entered.
- `SUBMITTED` — a member has submitted for PC registration; the submit gate
  (§3) has passed. The cartel keeps operating.
- `REGISTERED` — PC approved; the official cartel (semantically today's
  `OPEN`).
- A PC **decline** returns the cartel to `FORMING` and stores the PC note;
  edit-and-resubmit reuses the existing resubmit plumbing, re-entering
  `SUBMITTED`.

`ARCHIVED`/ended lifecycle (`Workgroup.archive()` / `Cartel.archive()`) is
unchanged and orthogonal — a cartel in any registration status can be archived.

### 2. Visibility & joining during FORMING

On propose, `Cartel.objects.propose(...)` creates the workgroup
**members-visible immediately** (`landing_visibility=members`,
`content_visibility=private`) instead of private. Consequences:

- The school sees the cartel exists (landing = members) and can **apply**
  (open call) via the existing `WorkgroupJoinRequest` flow.
- **Pre-selected** members named at propose time get `WorkgroupInvitation`s
  and are notified **immediately** (today they're only notified on PC
  approval — that notification moves earlier).
- A pure **open call** = propose with no invitees; a **mix** = propose with
  some invitees.
- The private channel/works are provisioned and available to accepted members
  throughout forming.
- `Cartel.closed` (close/reopen membership) works exactly as today, available
  in FORMING and after.

### 3. Submit-to-PC gate

New action `submit_for_registration` (any active cartelisand). It validates;
on failure it blocks and returns a checklist of what's missing; on success it
sets `registration_status=SUBMITTED` and notifies the PC + Coordinator. The
`WorkgroupProposal` row already exists (created at propose time — see §4); its
own status is synced to the PC-review portion of the flow at this point.

**Required (block submit):**

- **Plus-one assigned** — an internal `PLUS_ONE` membership *or* an
  `ExternalPlusOne` row exists.
- **Fixed period recorded** — `start_date` and `end_date` set, with
  `1 year ≤ (end − start) ≤ 2 years`. The 1–2yr bound is enforced **only at
  submit** (so a forming cartel can hold a rough window earlier).
- **Cartelisand count 3–5** — count active members **excluding** the plus-one;
  must be ≥ 3 and ≤ 5 (plus-one is extra, so up to 6 people total).

**Recommended (advisory in checklist, do NOT block):**

- **Per-member questions** — each cartelisand has entered their unique
  question. Shown as "N of M members have entered a question," never blocking
  (do-not-over-automate: keep the human escape hatch).

### 4. New data

Keep the shared Workgroup layer clean — cartel-specific data lives in the
`cartels` app:

- **`Cartel.registration_status`** — the TextChoices field from §1. This is
  the **source of truth** for the formation flow. The `WorkgroupProposal` row
  is still created at **propose** time (unchanged), so the existing proxied
  properties — `Cartel.generator` (= `proposal.proposed_by`), `reviewed_by`,
  `invitations`, `join_requests` — keep working throughout FORMING; the
  proposal's own `status` is just kept consistent with the PC-review portion
  and is no longer the driver.
- **`CartelQuestion`** — dedicated model, one row per (cartel, member):
  ```
  CartelQuestion
    cartel      FK(Cartel, related_name="member_questions")
    member      FK(User)
    text        TextField
    created_at  DateTimeField(auto_now_add)
    updated_at  DateTimeField(auto_now)
    unique_together (cartel, member)
  ```
  **Permissions:** a member edits **only their own** row; **all cartelisands
  (and the plus-one) can read all** rows. Included in the PC registration
  submission view.
- **Duration** reuses `Workgroup.start_date` / `end_date` (no new field); the
  1–2yr validator (§3) lives in the submit-gate code, not on the model, so it
  binds only at submit.

`Cartel.status` (the property proxying `WorkgroupProposal.status`) stays for
backward compatibility but the new `registration_status` is the source of
truth for the formation flow. The data migration (§7) sets it for existing
rows.

### 5. Coordinator & notifications

- **Coordinator** is notified when a cartel **starts forming** (on propose)
  and can leave advisory, non-binding feedback anytime via the existing
  `coordinator_feedback` view. They are **not** a gate.
- **PC** is notified at **submit** (not at propose). The existing
  "proposal → PC" notification/email moves to fire on `submit_for_registration`.
- Invitees are notified **on propose** (moved earlier from PC-approval).
- All other notifications (application, application decision, decision to
  generator) keep their triggers. Reuse existing categories; no new category
  needed (the `CARTEL_PROPOSAL` category now means "a cartel started forming").

### 6. UI

- Member-facing entry reframed from "propose to the PC" to **"start a cartel"**
  (forming). Copy uses commas, not em dashes, per the site-copy style rule.
- Cartel workspace (the `cartels/_overview.html` / `_settings.html` partials
  composed into the generic workgroup detail) gains:
  - a **per-member question** panel (edit-own, read-all);
  - a **formation checklist** rendering the submit gate (§3) — required items
    with pass/fail, recommended items advisory;
  - a **Submit for registration** button (any active member), enabled when the
    required gate passes; disabled with the checklist otherwise.
- The plus-one section is reframed as the deliberate late-stage "symbolic
  position" conversation → assignment (existing internal/external UI unchanged
  functionally).
- The PC registration submission/review view shows the entered details,
  including all per-member questions.

### 7. Testing & migration

**Data migration** (forward): map existing cartels by current proxied status —
`OPEN → REGISTERED`; `PROPOSED → SUBMITTED` (already at the PC); `DECLINED →
FORMING` (with note preserved). `ARCHIVED` cartels keep their archived
lifecycle and get `registration_status` from their pre-archive status where
resolvable, else `FORMING`.

**Tests** (pytest-django):

- Submit gate: each required validator (plus-one present/absent, duration
  in/out of 1–2yr bound and unset, count < 3 / in-range / > 5, plus-one
  correctly excluded from the count); recommended per-member questions never
  block.
- State transitions: propose → FORMING; submit → SUBMITTED; approve →
  REGISTERED; decline → FORMING + note; resubmit → SUBMITTED.
- Forming visibility: a forming cartel is members-visible and applyable;
  invitees notified on propose; PC notified only on submit.
- `CartelQuestion` permissions: member edits own only (403/blocked on others'),
  all cartelisands can read all.
- `closed` toggle still gates applications in FORMING and after.

**Out of scope (unchanged / deferred):** dissolution / permutation / the
"pass" (later lifecycle); external→internal plus-one signup conversion
(pre-existing gap); cadence/sessions (deliberate non-feature, decision G6).

## Files touched (anticipated)

- `cartels/models.py` — `Cartel.registration_status`, `CartelQuestion`,
  `submit_for_registration`, gate validators, `propose()` visibility change,
  transition helpers.
- `cartels/views.py` — submit view, per-member question edit view, wire
  notifications; adjust `review_decide` decline to return to FORMING.
- `cartels/forms.py` — per-member question form; propose form copy.
- `cartels/urls.py` — new routes (submit, question edit).
- `cartels/notifications.py` + `cartels/emails.py` — move PC notification to
  submit; add forming-start Coordinator notification.
- `cartels/templates/cartels/_overview.html`, `_settings.html`, `propose.html`,
  `review_queue.html` (+ any submission detail template) — checklist, question
  panel, submit button, copy.
- `cartels/permissions.py` — question edit permission helper if needed.
- `cartels/migrations/` — schema (new field + model) + data migration.
- `cartels/tests.py` — new tests above.
