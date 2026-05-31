# Design note — Workgroups (shared collaborative-group layer)

Implements the decisions in `../LSP-Website-Workgroups-Design.md` (the
worksheet). This is the build-facing spec. Memory: `workgroups-architecture`.

## Principle (load-bearing)

Cartels, working groups, committees, and seminars all want the same
collaborative layer (roster + channel + works + files + a landing page).
A single **`Workgroup`** model owns that layer; domain models **attach** one
via `OneToOneField`. **When adding any group feature, put it on `Workgroup`
first** — only reach for the specific model when the thing is genuinely
type-specific.

## Models

### `workgroups` app

```python
class Workgroup(Model):
    class Kind(TextChoices):
        CARTEL, WORKING_GROUP, COMMITTEE, SEMINAR
    class Visibility(TextChoices):      # 3 levels (vs. works' 2)
        PUBLIC   = "public"             # anyone
        MEMBERS  = "members"            # any logged-in LSP member ("Open" in the worksheet)
        PRIVATE  = "private"            # only this workgroup's members

    kind                 = CharField(choices=Kind)
    name                 = CharField
    slug                 = SlugField(unique=True)
    description          = TextField(blank=True)        # markdown

    landing_visibility   = CharField(choices=Visibility, default=MEMBERS)  # who sees it exists
    content_visibility   = CharField(choices=Visibility, default=PRIVATE)  # who sees roster/works/files
    # invariant (clean()): content_visibility may not be MORE public than landing_visibility

    start_date           = DateField(null=True, blank=True)
    end_date             = DateField(null=True, blank=True)   # null = standing/ongoing
    parent               = FK("self", null=True, blank=True, related_name="children")  # nesting (v1: link only)

    # capability toggles — defaulted per kind at creation, fully editable after
    has_channel   = BooleanField(default=True)
    has_works     = BooleanField(default=True)
    has_files     = BooleanField(default=True)
    has_calendar  = BooleanField(default=False)
    has_minutes   = BooleanField(default=False)
    has_tasks     = BooleanField(default=False)
    has_decisions = BooleanField(default=False)

    created_at = DateTimeField(auto_now_add=True)

    def is_member(self, user) -> bool: ...   # access primitive (see below)
    def active_members(self): ...            # WorkgroupMembership where end_date is null
```

`is_member` is the **one access primitive** the cross-cutting apps call. For
self-managed kinds it checks `WorkgroupMembership`; a seminar-attached
workgroup derives its roster (Stage 5) — `is_member` dispatches to the
attached `Event` rather than reading rows. Keep the dispatch in one place.

Capability defaults by kind (the worksheet's Table A, as the seed):

| kind | channel | works | files | calendar | minutes | tasks | decisions |
|---|---|---|---|---|---|---|---|
| cartel | Y | Y | Y | Y | N | Y | N |
| working_group | Y | Y | Y | Y | Y | Y | Y |
| committee | Y | Y | Y | Y | Y | Y | Y |
| seminar | Y | N | Y | Y | N | N | N |

### `WorkgroupMembership` (the unified roster)

Generalizes today's `committees.CommitteeMembership` exactly — same shape,
same partial-unique constraint.

```python
class WorkgroupMembership(Model):
    class Role(TextChoices):
        MEMBER, CHAIR, CO_CHAIR, SECRETARY, TREASURER, PLUS_ONE,
        REFERRAL_COORDINATOR, WEB_COORDINATOR, ADMIN_ASSISTANT   # last three for committee fold-in
    workgroup  = FK(Workgroup, related_name="memberships")
    user       = FK(AUTH_USER_MODEL, related_name="workgroup_memberships")
    role       = CharField(choices=Role, default=MEMBER)
    start_date = DateField()
    end_date   = DateField(null=True, blank=True)   # null = currently serving
    # UniqueConstraint(user, workgroup) WHERE end_date IS NULL  (one active per pair)
```

The cartel **plus-one** is just `role=PLUS_ONE` — no field on `Cartel`.

### `cartels` app

```python
class Cartel(Model):
    workgroup = OneToOneField(Workgroup, related_name="cartel")
    # starts thin (per the locked honest-caveat); grows cartel-specific bits:
    #   - CART-4 formation status / workflow
    #   - guiding question / trait, the cartel "product" link
```

This is the canonical **attach** exemplar that Committee and Seminar follow.
A cartel is created as `Workgroup(kind=CARTEL)` + an attached `Cartel`
(helper `Cartel.objects.create_with_workgroup(...)`).

## Cross-cutting wiring (the payoff: one FK, not one-per-type)

### `works.Work`

- Add `workgroup = FK(Workgroup, null=True, blank=True, related_name="works")`.
- Add `Visibility.GROUP = "group"` (visible to the work's workgroup members).
- `listing_visible_to` / `pdf_visible_to` / `listing_for` gain a `GROUP`
  branch: `self.workgroup and self.workgroup.is_member(user)`.
- `clean()` invariant extends: a `GROUP` work must have a `workgroup`.
- Form: un-hide the `CARTEL` kind (currently hidden per `works/models.py`
  header comment); show a workgroup picker when visibility=GROUP.
- **Replaces the planned `Work.cartel` FK** from the old M14 brief.

### Parlêtre `Channel`  (Stage 2 — additive against merged code)

Current `Channel.Access` = OPEN / ROLE / COMMITTEE / PRIVATE with
`committee` FK + `members` M2M (read in `parletre/permissions.py`). Add:

- `Access.WORKGROUP = "workgroup"` + `workgroup = FK(Workgroup, null=True, related_name="channels")`.
- `permissions.channel_visible`: branch `access == WORKGROUP → channel.workgroup and channel.workgroup.is_member(user)`.
- `permissions.channel_can_moderate`: workgroup CHAIR / CO_CHAIR / PLUS_ONE
  moderate (mirrors the existing committee-chair branch).
- **Open sub-decision:** does a workgroup channel allow the staff bypass
  (like COMMITTEE) or is it genuinely private with no bypass (like PRIVATE)?
  Cartels lean genuinely-private → likely *no* bypass for cartel channels,
  bypass for committee channels. Probably keyed off `workgroup.kind` or a
  `private` flag. **Decide at Stage 2.**
- Auto-provision: creating a `Workgroup` with `has_channel=True` creates one
  `Channel(access=WORKGROUP, workgroup=…, kind=FORUM)`. Signal or in the
  create helper.
- The existing `COMMITTEE` access stays working; it migrates to `WORKGROUP`
  when committees fold in (Stage 4). Nothing in Parlêtre breaks before then.

## Staged build plan

**Stage 1 — `workgroups` foundation + Cartels MVP (this stream). ✅ DONE.**
`workgroups` app (Workgroup + WorkgroupMembership + admin + migrations +
`is_member`/visibility helpers). Workspace surface at `/groups/` (list +
detail: about / roster / output, gated by visibility + membership — sections,
not JS tabs, for MVP). `cartels` app (Cartel attach + `create_with_workgroup`
helper, `/cartels/` list, landing reuses the workspace surface, nav link).
Wired `Work.workgroup` + `Visibility.GROUP` + form (CARTEL kind un-hidden,
group picker limited to the user's groups). Rationalized `works` "Members
only" to mean `is_lsp_member` (consistent with Workgroup). 30 new tests.
Dockerfile template-COPY list updated. **Delivers the original M14 goal
(cartel-internal works) on the new layer.**

  *Deferred from Stage 1 (intentionally):* a `WorkgroupFile` model (the
  `has_files` toggle exists but no file surface yet); JS tabs; per-kind
  Workspace copy; seeded demo cartels on prod.

**Stage 2 — Parlêtre integration.** `Channel.workgroup` + `access=workgroup`
+ permission branches + auto-provision per workgroup. Settle the
staff-bypass sub-decision. Tests.

**Stage 3 — Working groups.** `kind=working_group` config (standing, chair
role, Open landing / private contents) + any WG-specific view copy. Mostly
configuration once the foundation exists.

**Stage 4 — Committee fold-in (risk-managed).** Migrate `committees` data →
`Workgroup(kind=committee)` + `WorkgroupMembership`; repoint permission reads
in `committees` and `parletre/permissions.py` (the `CommitteeMembership`
queries) to the unified roster; convert `Channel.access=committee` →
`workgroup`. Keep a thin `Committee` model attached for its charter /
public-page semantics. Data migration + thorough tests. Its own deploy.

**Stage 5 — Seminar attachment.** `Event.workgroup` OneToOne (nullable);
`Workgroup.is_member` dispatches to the Event's faculty + paid registrants;
default toggles = channel + files, no shared-works.

## Migration order (all of Stage 1–2 is additive)

1. `workgroups/0001` — Workgroup + WorkgroupMembership.
2. `cartels/0001` — Cartel.
3. `works/000N` — add `workgroup` FK + `GROUP` visibility value.
4. `parletre/000N` (Stage 2) — add `workgroup` FK + `WORKGROUP` access value.

No existing-data migration until Stage 4. New app templates dirs must be
added to the Dockerfile stage-2 COPY list (see `dockerfile-css-build…`
memory) or Tailwind drops their classes in prod.

## Open sub-decisions (surface before/at the relevant stage)

- **S1:** Confirm 3-level visibility (Public / Members / Private), two-axis
  (landing vs. content), with the "content ≤ landing" invariant.
- **S2:** Workgroup-channel staff bypass — per-kind, or a `private` flag?
- **S4:** "LSP Staff" committee — fold to a Parlêtre channel, or keep as a
  committee-kind workgroup?
- **General:** does `Cartel` warrant its own app now, or live inside
  `workgroups` until it grows? (Recommend own app — CART-* views land there.)
