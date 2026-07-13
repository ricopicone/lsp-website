# Shared school officers: President / Vice President synced across the Board and the Meeting of Analysts

**Task #428 (follow-on).** Date: 2026-07-12.

## Problem

The President and Vice President are school officers who lead **both** the Board
of Directors and the Meeting of Analysts (MoA). Today that shared leadership has
two independent, desyncable representations:

1. **Board workgroup memberships** — `Chair` / `Co-chair` rows on the Board
   committee's workgroup (from `seed_committees`), edited in the Board workspace
   → Settings roster. These drive the relabeled "President / Vice President" on
   the Board roster, the directory, and the About page (via `OFFICER_TITLES` /
   `role_label`, task #428).
2. **President / Vice-President `StaffRole`s** — appointed *separately* in
   **Board → Appointments** (`core.staff.board_appointments`). Their holders
   drive the "School officers" panel shown on both the Board and MoA admin pages
   and back the permission checks.

Nothing keeps (1) and (2) in sync: you can set the Board's Chair without
changing the President StaffRole, or vice versa. There is no single control
point, and the MoA has no visible officers on its own workspace roster (it is
auto-membership — every analyst is a plain `Member`).

## Goal

- **One control point:** the Board workspace → Settings roster. Setting the
  Board's `Chair` = President; `Co-chair` = Vice President.
- **Synchronized:** the President / Vice-President `StaffRole`s always mirror the
  Board's current Chair / Co-chair.
- **MoA reflects it:** the Meeting of Analysts workspace roster shows the same
  President / Vice President as leaders (chips), derived from the shared
  appointment — never settable independently on the MoA.

Non-goals: the Programming Committee's Chair (stored `chair`, styled "Convener"
in seed comments but **displayed as "Chair"** — which is correct and stays as
is). No change to any other StaffRole in Appointments (Treasurer, Web
Coordinator, Cartel Coordinator, Admin Assistant, Web Developer, LSP Staff).

## Design

### 1. Source of truth + sync

The Board's `Chair` / `Co-chair` `WorkgroupMembership` rows are the sole edit
surface. A single idempotent function keeps the StaffRoles in lockstep:

```
# committees/officers.py
def sync_school_officers():
    """President StaffRole holders := users currently serving as the Board's
    Chair; Vice-President holders := the Board's Co-chair. Recomputed from the
    Board roster and .set() on each role, so it is idempotent and self-healing."""
    board = Committee.objects.filter(slug="board").select_related("workgroup").first()
    if board is None or board.workgroup_id is None:
        return
    serving = list(board.workgroup.memberships.serving().select_related("user"))
    mapping = {
        WorkgroupMembership.Role.CHAIR:    StaffRole.PRESIDENT,
        WorkgroupMembership.Role.CO_CHAIR: StaffRole.VICE_PRESIDENT,
    }
    for role_value, key in mapping.items():
        holders = [m.user for m in serving if m.role == role_value]
        sr = StaffRole.objects.filter(key=key).first()
        if sr is not None:
            sr.holders.set(holders)
```

**Trigger.** A `post_save` + `post_delete` signal on
`workgroups.WorkgroupMembership`, connected in `committees/apps.py` `ready()`
(handler in `committees/signals.py`). The handler early-returns unless
`instance.role in {CHAIR, CO_CHAIR}` (cheap string check, no query) **and** the
membership's workgroup is the Board committee's workgroup; then it calls
`sync_school_officers()`. This covers every write path: the Settings-tab roster
views (`roster_add` / `roster_remove` / `set_role`), the Django admin, and
`seed_committees`. Leaving a role (setting `end_date`) is a `save`, so
`serving()` drops the row and the StaffRole is recomputed.

Rationale for signal-over-view-hook: the Board roster is editable from several
places; a model signal is the one chokepoint that can't be bypassed.

Sync direction is **Board roster → StaffRole** only. The StaffRole is now a
mirror, never a separate appointment.

### 2. Meeting of Analysts shows the officers as leaders (derived)

`Workgroup.participants()`, **for the MoA committee only** (slug
`meeting-of-analysts`), injects the President / Vice President as *lead*
participants after the auto-member loop, overwriting their plain `Member` row:

- Officers are read from the synced StaffRoles (`StaffRole.PRESIDENT` /
  `VICE_PRESIDENT` holders) — the canonical school-officer record.
- Each is injected as `Participant(user=u, role=Role.CHAIR|CO_CHAIR,
  is_lead=True, officer_title="President"|"Vice President")`. Reusing the
  `CHAIR` / `CO_CHAIR` role values makes them sort first
  (`ROLE_RANK` = 1 / 2) and read as leaders; `role != "member"` makes the chip
  show.

**`Participant` gets one new optional field, `officer_title`.** Its `role_label`
property prefers it:

```
officer_title: str | None = None
@property
def role_label(self):
    if self.officer_title:
        return self.officer_title
    if self.membership is not None:
        return self.membership.role_label
    return self.get_role_display()
```

Derived officer rows carry no `membership`, so without this override they would
read "Chair" instead of "President". Stored rows (Board members, MoA
Applications Coordinator) are unaffected — `officer_title` is `None` and they
fall through to `membership.role_label` exactly as today.

The MoA roster is committee-kind → publicly visible, so the President / Vice
President appear as public leader chips on `/groups/meeting-of-analysts/`, which
is intended (they are public officers).

The MoA Settings tab already offers no chair/co-chair assignment (auto-member
groups only assign Applications Coordinator via `assignable_roles`), so the
officers are inherently read-only there. Add a one-line pointer on the MoA
overview/settings: *"President and Vice President are set in the Board's
Settings roster."*

### 3. Board → Appointments drops President / Vice President

- `board_appointments` filters `StaffRole.PRESIDENT` / `VICE_PRESIDENT` out of
  the `roles` it lists (POST for those keys is likewise rejected, defensively).
- `_officers.html` note text changes from *"Appointed once in Board →
  Appointments; governs the Board and the Meeting of Analysts both."* to
  *"Set in the Board's Settings roster (Chair = President, Co-chair = Vice
  President); governs the Board and the Meeting of Analysts both."*
- `board_appointments.html` copy that references appointing officers is updated
  to point at the Board Settings roster for President / Vice President.

### 4. One-time reconciliation

A data migration (`committees`) calls `sync_school_officers()` once so
production converges on deploy. In practice a no-op — Christopher Meyer is both
Board Chair and President, Beatrice Patsalides Hofmann both Co-chair and Vice
President.

**Intended consequence (documented):** the Board roster is the tie-breaker. If a
President StaffRole holder ever disagrees with the Board's Chair, the next sync
replaces the StaffRole holders with the Board's Chair. This is the point of the
change — one source of truth.

## Files touched

- `committees/officers.py` — new `sync_school_officers()`.
- `committees/signals.py` — new signal handler.
- `committees/apps.py` — connect signals in `ready()`.
- `committees/migrations/00XX_sync_school_officers.py` — one-time reconcile.
- `workgroups/models.py` — `Participant.officer_title` field + `role_label`
  update; MoA officer injection in `participants()`; add
  `"meeting-of-analysts"` handling (via the injected `officer_title`, so
  `OFFICER_TITLES` itself need not gain a key).
- `core/staff.py` — `board_appointments` excludes President / VP.
- `core/templates/core/staff/admin/_officers.html` — note text.
- `core/templates/core/staff/admin/board_appointments.html` — copy.
- MoA overview/settings pointer (template).
- Tests in `committees/tests.py` and `workgroups/tests.py`.

## Testing

1. **Sync on appoint:** add a Board `Chair` membership → the President StaffRole
   holder becomes that user. Add a `Co-chair` → Vice-President holder set.
2. **Sync on change:** change the Chair to a different user → President holders
   follow (old holder dropped).
3. **Sync on leave/remove:** end the Chair membership → President holders empty.
4. **Non-Board unaffected:** setting a Programming Committee `Chair` does **not**
   touch the President StaffRole; PC roster still displays "Chair".
5. **MoA display:** with a synced President/VP, the MoA workspace roster renders
   them as leader chips titled President / Vice President, sorted first; a plain
   analyst still shows as a `Member`.
6. **Appointments:** `board_appointments` no longer lists President / Vice
   President; posting those keys is rejected.
7. **Reconcile migration:** running it with an out-of-sync StaffRole holder
   converges the holders to the Board roster.
