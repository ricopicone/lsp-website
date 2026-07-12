# Formation-tab formation-doc link (task #416)

## Goal

At the top of **My LSP → Formation**, surface a link to the member's
track-appropriate formation guidelines document:

- Analyst-track members in training (pre-candidate analyst, candidate analyst)
  see a link to the **Analyst Formation Guidelines**.
- Scholar-track members in training (pre-candidate scholar, candidate scholar)
  see a link to the **Scholar Formation Guidelines**.

Graduated analysts/scholars and non-track roles (plain member, faculty-only)
see nothing. Nothing renders if the target document is unset or not visible to
the member.

## Decisions (settled during brainstorming)

- **Audience: in-training only.** Gate on `Profile.IN_TRAINING_ROLES`
  (`pre_candidate`, `candidate`, `pre_candidate_scholar`, `candidate_scholar`),
  not the whole track. Graduated `analyst`/`scholar` do not see the link.
- **Reference: configurable in admin.** Two nullable FKs on the
  `FormationSettings` singleton point at `documents.Document` rows, so staff can
  repoint each track's link without a code change. A data migration sets the
  sensible defaults from the seeded slugs.

## The existing pieces this builds on

- The Formation tab is `formation/templates/formation/_tab_formation.html`,
  built by `_formation_context()` in `formation/views.py`. Its advisor/steps
  context is always built (it is the default tab), so adding one more cheap
  value there costs nothing extra.
- `FormationSettings` (`formation/models.py`) is the pk=1 singleton already
  loaded in `_formation_context` for `control_years_target`.
- The two documents already exist, seeded with stable slugs
  (`documents/management/commands/seed_documents.py`):
  - `analyst-formation-guidelines` — "Analyst Formation Guidelines"
  - `scholar-formation-guidelines` — "Scholar Formation Guidelines"
  - Addressable via `Document.get_absolute_url` (`/documents/<slug>/`), with a
    gated download view behind it. Visibility helpers:
    `Document.listing_visible_to(user)`.
- Track membership is derivable from role via `Profile.ANALYST_TRACK_ROLES` /
  `Profile.SCHOLAR_TRACK_ROLES`.

## Changes

### 1. Model — `formation/models.py`

Add two nullable FKs to `FormationSettings`:

```python
analyst_formation_doc = models.ForeignKey(
    "documents.Document", null=True, blank=True, on_delete=models.SET_NULL,
    related_name="+",
    help_text="Formation guidelines linked at the top of the Formation tab "
              "for analyst-track members in training.",
)
scholar_formation_doc = models.ForeignKey(
    "documents.Document", null=True, blank=True, on_delete=models.SET_NULL,
    related_name="+",
    help_text="Formation guidelines linked at the top of the Formation tab "
              "for scholar-track members in training.",
)
```

`on_delete=SET_NULL` so deleting a Document just hides the link rather than
cascading into settings. `related_name="+"` — no reverse accessor needed.

### 2. Migrations — `formation/migrations/`

- Schema migration adding the two FKs.
- Data migration (`RunPython`, reversible with `noop`) that, on the loaded
  singleton, sets `analyst_formation_doc` to the `analyst-formation-guidelines`
  Document and `scholar_formation_doc` to `scholar-formation-guidelines` **when
  those rows exist and the field is currently null**. Uses
  `apps.get_model("documents", "Document")` and `.filter(slug=...).first()` so
  a missing doc is a no-op, never a crash. Idempotent.

### 3. Admin — `formation/admin.py`

Replace `admin.site.register(FormationSettings)` with a `ModelAdmin` exposing
`control_years_target`, `analyst_formation_doc`, `scholar_formation_doc` (plain
FK selects — the document set is small).

### 4. View — `formation/views.py`

Add a module-level helper:

```python
def _formation_doc_for(user):
    """The track-appropriate formation guidelines Document for an in-training
    member, or None. In-training only; respects the doc's listing visibility."""
    profile = getattr(user, "profile", None)
    if profile is None or profile.role not in Profile.IN_TRAINING_ROLES:
        return None
    settings_obj = FormationSettings.load()
    if profile.role in Profile.ANALYST_TRACK_ROLES:
        doc = settings_obj.analyst_formation_doc
    elif profile.role in Profile.SCHOLAR_TRACK_ROLES:
        doc = settings_obj.scholar_formation_doc
    else:
        doc = None
    if doc is not None and doc.listing_visible_to(user):
        return doc
    return None
```

`_formation_context` already calls `FormationSettings.load()` for
`control_target`; reuse that instance to avoid a second query, then set
`ctx["formation_doc"] = _formation_doc_for(user)`.

Since `IN_TRAINING_ROLES ⊂ (ANALYST_TRACK_ROLES ∪ SCHOLAR_TRACK_ROLES)`, the
`else` branch is defensive only.

### 5. Template — `formation/templates/formation/_tab_formation.html`

At the very top of the `space-y-6` wrapper, before the Advisor `<section>`:

```html
{% if formation_doc %}
<a href="{{ formation_doc.get_absolute_url }}"
   class="flex items-start gap-3 rounded-xl border border-primary/30 bg-primary/5 p-5 hover:bg-primary/10 transition-colors scroll-mt-24">
  <span class="min-w-0">
    <span class="block font-serif text-lg text-base-content">{{ formation_doc.title }}</span>
    <span class="block text-sm text-base-content/70">
      {% if formation_doc.summary %}{{ formation_doc.summary }} {% endif %}Read the guidelines for your formation pathway. &rarr;
    </span>
  </span>
</a>
{% endif %}
```

DaisyUI semantic tokens throughout; member-facing copy uses commas, not em
dashes (per the em-dash-prose-style exception for site copy).

### 6. Tests — `formation/test_my_lsp.py`

The seeded documents are not created in the test DB (the data migration is a
no-op without them), so each test creates a `Document` and sets the FK on
`FormationSettings` explicitly. Then assert:

- In-training analyst-track member (`pre_candidate`) → response contains the
  analyst doc's URL.
- In-training scholar-track member (`pre_candidate_scholar`) → response
  contains the scholar doc's URL.
- Graduated `analyst` and plain `member` → neither doc URL present.
- FK null → link absent (context `formation_doc is None`).

## Out of scope

- No changes to the Documents app, the seeded PDFs, or document visibility.
- No new document categories or upload flow.
- No change to which tabs appear or their ordering.
