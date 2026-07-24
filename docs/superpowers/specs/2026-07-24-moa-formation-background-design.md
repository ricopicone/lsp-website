# MoA-owned formation background — design

**Task:** #466 — Formation-hour tracker doesn't reflect clinical-track requirements
**Date:** 2026-07-24

## Problem

The formation control-analysis tracker (My LSP → Formation → Control) shows each
student a control requirement that *already* varies by background:

- **Clinical background** → one 4-year + one 2-year control = **6 years**
- **Academic background** → one 4-year + two 2-year controls = **8 years**

The requirement is keyed off `Profile.clinical_background`, a boolean that
**defaults `False`** and is only set "at acceptance from the application." The
field was added after the member roster was imported, so essentially every
in-training member is still at the default — and `False` conflates *"academic"*
with *"never reviewed."* Result: clinically-backgrounded students (e.g. Garret
Barnwell) are silently shown the stricter 8-year academic requirement.

Two problems to fix:

1. **Ownership + auditability.** Setting a student's background is a formation
   decision, and formation is the Meeting of Analysts' (MoA) charge. Today it's
   a bare, unaudited checkbox on the *advisor's* advisee page. It needs to be a
   first-class, auditable surface with an optional note on every change.
2. **The silent default.** `False` should not mean "academic." An explicit
   *unreviewed* state removes the conflation and gives the MoA a worklist of
   students still needing a determination.

## Decisions (from brainstorming)

- **Authority:** both the MoA *and* the student's current advisor may set it,
  but every change routes through one audited flow (actor / timestamp / note).
- **States:** 3-state — `UNREVIEWED` (default) / `CLINICAL` / `ACADEMIC`.
- **Student notification:** in-app bell on every actual change (email opt-in).

## Data model

### Widen the field (`accounts/models.py`)

Rename `Profile.clinical_background` (BooleanField) →
`Profile.formation_background`, a `TextChoices`:

```python
class FormationBackground(models.TextChoices):
    UNREVIEWED = "unreviewed", "Not yet reviewed"
    CLINICAL   = "clinical",   "Clinical (2 control analyses: one 4-year, one 2-year)"
    ACADEMIC   = "academic",   "Academic (3 control analyses: one 4-year, two 2-year)"

formation_background = models.CharField(
    max_length=12, choices=FormationBackground.choices,
    default=FormationBackground.UNREVIEWED,
    help_text="The student's professional background, which sets the control-"
              "analysis requirement. Determined by the Meeting of Analysts (or "
              "the student's advisor). Independent of the formation track.",
)
```

### Audit model (`formation/models.py`)

```python
class BackgroundDetermination(models.Model):
    """Immutable audit row: one per actual change to a student's
    formation_background. Profile holds the current (denormalized) value; this
    table is the history — same live-value + audit-row pattern as
    EventChangeRequest."""
    member     = FK(User, related_name="background_determinations", on_delete=CASCADE)
    background  = CharField(choices=Profile.FormationBackground.choices)  # value set
    previous    = CharField(choices=..., blank=True)                      # prior value
    set_by      = FK(User, related_name="+", on_delete=SET_NULL, null=True)
    created_at  = DateTimeField(auto_now_add=True)
    note        = TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
```

### Data migration

Transform existing rows, then drop the old column:

- `clinical_background = True`  → `formation_background = CLINICAL`
- `clinical_background = False` → `formation_background = UNREVIEWED`

No `BackgroundDetermination` rows are synthesized — pre-existing values were not
real determinations. Net effect: every un-set student (incl. Garret) becomes
`UNREVIEWED` and appears on the MoA worklist, to be set through the new surface.
This is the intended "wait for the surface" path — the first real determination
for Garret happens there, audited, with a note.

## Requirement logic

`Profile.control_requirement()`:

- `CLINICAL`   → `{"four_year": 1, "two_year": 1}` (6 yr)
- `ACADEMIC`   → `{"four_year": 1, "two_year": 2}` (8 yr)
- `UNREVIEWED` → `None`

`formation/control.py::control_progress(user)`:

- When `control_requirement()` is `None`, return `{"reviewed": False,
  "total_years": <sum of logged entries>, "entries": [...]}` — no `total_target`
  / slot bars.
- Otherwise unchanged (`reviewed": True` plus the existing `total_years`,
  `total_target`, `four_year`, `two_year` keys).

## Shared service (`formation/background.py`)

Single write path both surfaces call:

```python
def set_background(member, value, *, by, note="") -> BackgroundDetermination | None:
    old = member.profile.formation_background
    if value == old:
        return None                       # no-op: nothing recorded, no notify
    member.profile.formation_background = value
    member.profile.save(update_fields=["formation_background"])
    row = BackgroundDetermination.objects.create(
        member=member, background=value, previous=old, set_by=by, note=note.strip(),
    )
    notifications.background_set(member, row)   # in-app bell (see below)
    return row
```

- `value` is only ever `CLINICAL` or `ACADEMIC` (the UI never offers
  `UNREVIEWED` — it's the initial state, not a choice).
- `note` is optional; when present it's stored on the audit row.

## Entry points (both audited)

### 1. MoA surface — new console page

- URL: `/admin-tools/meeting-of-analysts/backgrounds/`
  (`formation:background_queue`), gated by `admissions.views._require_review`
  (Analysts + staff/superuser), matching the other MoA surfaces.
- **List** (`background_queue`): in-training students (`IN_TRAINING_ROLES`),
  **unreviewed first**, each showing name, role/track, current background badge,
  who/when last set, an inline set-form (Clinical / Academic radio + optional
  note), and a link to per-student history.
- **History/detail** (`background_detail`, `backgrounds/<pk>/`): the student's
  `BackgroundDetermination` log + the set-form.
- **MoA landing** (`core/staff.py::meeting_of_analysts_admin` +
  `core/templates/core/staff/admin/meeting_of_analysts.html`): add a
  **Backgrounds** card showing the count of in-training students still
  `UNREVIEWED` (`open_backgrounds`).

### 2. Advisor surface — upgrade the existing control

- `advisee_detail.html` (~line 66): replace the bare checkbox with the same
  Clinical / Academic radio + optional-note form.
- `formation/views.py::advisee_set_background`: post through `set_background(...)`
  instead of writing the boolean directly. Gate unchanged (`can_view_advisee` =
  current advisor or staff). Show recent history / who-last-set on the page.

## Student-facing

### Tracker (`formation/templates/formation/_tab_formation.html`)

- `control_progress.reviewed is False` → neutral panel: *"Your control-analysis
  requirement will be set by the Meeting of Analysts."* The control-analysis log
  and "Add a control analysis" remain usable (entries + total years still show);
  the target bar and slot sub-bars are hidden.
- Reviewed → renders as today, with the correct 6/8-year target.

### Notification

- New category `FORMATION_BACKGROUND` in `notifications/categories.py`
  (`Category` enum **and** the `CategoryMeta` registry): in-app default on, email
  opt-in (not locked), grouped under the Formation/Account section.
- `formation/notifications.py::background_set(member, row)` → `notify(member,
  Category.FORMATION_BACKGROUND, title="Your formation control requirement has
  been set to <clinical/academic>", url=reverse("formation:formation") +
  "#control", target=row, email_fn=...)`. Fired only on an actual change.

## Testing

- `control_requirement()` / `control_progress()` across all 3 states (incl. the
  `reviewed=False` payload for `UNREVIEWED`).
- `set_background`: writes an audit row, updates the profile, notifies the
  student, and no-ops (records nothing, no notify) when the value is unchanged.
- MoA surface: gated (Analyst allowed, plain member 403), lists in-training
  students unreviewed-first, sets a background with note, worklist count on the
  landing.
- Advisor surface: the current advisor sets a background through the audited
  flow; note is recorded; non-advisor denied.
- Data migration: `True → CLINICAL`, `False → UNREVIEWED`.
- Notification fired to the student on change; category present in preferences.
- Tracker template: neutral state when unreviewed; correct target when set.

## Out of scope (YAGNI)

- Member-initiated "flag a mismatch" flow (student self-report). Not requested;
  the advisor path already covers Garret's case.
- A separate MoA *decision queue* (request → approve). Background is an
  MoA-asserted fact, not a member-initiated request — a registry with history
  fits, not a queue.
- Backfilling `BackgroundDetermination` history for the migration.

## Files touched (anticipated)

- `accounts/models.py` — field rename/widen, `FormationBackground`,
  `control_requirement()`.
- `accounts/migrations/00XX_*` — schema + data migration.
- `accounts/admin.py` — `list_display` / `list_filter` (`formation_background`).
- `formation/models.py` — `BackgroundDetermination` (+ migration).
- `formation/background.py` — new `set_background` service.
- `formation/control.py` — `control_progress` unreviewed payload.
- `formation/views.py` — `background_queue`, `background_detail`,
  upgraded `advisee_set_background`.
- `formation/urls.py` — new MoA routes.
- `formation/notifications.py` — `background_set`.
- `notifications/categories.py` — `FORMATION_BACKGROUND`.
- `core/staff.py` + `meeting_of_analysts.html` — Backgrounds card + count.
- `formation/templates/formation/` — `background_queue.html`,
  `background_detail.html`, upgraded `advisee_detail.html`, `_tab_formation.html`.
- Tests across `accounts/` and `formation/`.
