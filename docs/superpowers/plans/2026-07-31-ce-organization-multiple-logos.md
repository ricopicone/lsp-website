# Multiple Logos per CE Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a CE accrediting organization carry up to 10 logos instead of one, added through an "Add another logo" button, with a per-organization page where an existing organization's logo set, URL, and statement can be edited.

**Architecture:** `CEOrganization.logo` (a single `ImageField`) is replaced by a related `CEOrganizationLogo` model, with a data migration moving each existing logo onto a first row. Both editing surfaces — the existing create form and a new per-organization page — share one `MultipleFileField`, one validation helper, and one `CEOrganization.add_logos()` model method.

**Tech Stack:** Django 5.2, pytest-django, Pillow, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-07-31-ce-organization-multiple-logos-design.md`

## Global Constraints

- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both green before every commit.
- Serialize a test run with `-n 0` (addopts sets `-n auto`; `-p no:xdist` breaks the flag and errors).
- Python line length 100 (ruff `E`, `F`, `I`, `UP`).
- **Tailwind classes set in Python must also appear literally in some `.html` file** or the production build drops them. Every widget class here (`input input-bordered input-sm`, `textarea textarea-bordered`, `file-input file-input-sm`) already appears in existing templates.
- **Multi-line `{# #}` template comments are banned** (`core/test_templates.py::test_no_multiline_hash_comments_in_templates`). Use `{% comment %}`/`{% endcomment %}`.
- Adding a field to a `ModelForm` makes it **required** unless the model sets `blank=True` — check every existing POST path before adding one.
- `{{ obj.image.url }}` raises `ValueError` on an empty field. Guard with `{% if %}` or iterate a set.
- Member-facing copy uses commas, not em dashes.
- Cap is **10 logos per organization**, named once as `events.ce_images.MAX_LOGOS`.
- Worktree is `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/calm-willow`.

---

### Task 1: The logo model and the migration off the single field

**Files:**
- Modify: `events/models.py` (add `CEOrganizationLogo` after `CEOrganization`; remove `CEOrganization.logo`; add `CEOrganization.add_logos()`)
- Create: `events/migrations/0040_ce_organization_logos.py` (generated, then hand-edited to add the data step)
- Test: `events/test_ce.py` (append)

**Interfaces:**
- Consumes: `events.models.CEOrganization` (shipped in task #486).
- Produces:
  - `events.models.CEOrganizationLogo` with fields `organization` (FK, `related_name="logos"`), `image`, `sort_order`, `created_at`; `Meta.ordering = ("sort_order", "pk")`.
  - `CEOrganization.add_logos(blobs) -> list[CEOrganizationLogo]`, where `blobs` is a list of `django.core.files.base.ContentFile` (the output of `normalize_logo`). Appends after the current highest `sort_order`.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_ce.py`:

```python
# ---- Logo set ----------------------------------------------------------


def _webp_blob():
    """A tiny real WebP, the shape normalize_logo() returns."""
    import io

    from django.core.files.base import ContentFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())


@pytest.mark.django_db
def test_add_logos_appends_in_order(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="APA")

    org.add_logos([_webp_blob(), _webp_blob()])
    org.add_logos([_webp_blob()])

    logos = list(org.logos.all())
    assert len(logos) == 3
    assert [logo.sort_order for logo in logos] == [1, 2, 3]
    assert all(logo.image.name.endswith(".webp") for logo in logos)


@pytest.mark.django_db
def test_deleting_an_organization_takes_its_logos(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA")
    org.add_logos([_webp_blob()])
    org.delete()
    assert CEOrganizationLogo.objects.count() == 0


@pytest.mark.django_db
def test_the_single_logo_field_is_gone():
    """Its replacement is the related set; a stray `logo` attribute would mean
    the migration left the old column behind."""
    field_names = {f.name for f in CEOrganization._meta.get_fields()}
    assert "logo" not in field_names
    assert "logos" in field_names
```

Add `CEOrganizationLogo` to the existing `from events.models import ...` line at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce.py -q -n 0`
Expected: FAIL, `ImportError: cannot import name 'CEOrganizationLogo'`.

- [ ] **Step 3: Add the model and the helper**

In `events/models.py`, replace the `logo` field on `CEOrganization` — delete this line entirely:

```python
    logo = models.ImageField(upload_to="ce-organizations/")
```

Then add this method to `CEOrganization`, after `__str__`:

```python
    def add_logos(self, blobs):
        """Append normalized WebP blobs as logo rows, after the current last.

        ``blobs`` are the ContentFiles ``ce_images.normalize_logo`` returns, so
        both editing surfaces store identical, already-bounded images.
        """
        from django.utils.text import slugify

        start = (self.logos.aggregate(models.Max("sort_order"))["sort_order__max"] or 0) + 1
        stem = slugify(self.name) or "ce-organization"
        created = []
        for offset, blob in enumerate(blobs):
            order = start + offset
            logo = CEOrganizationLogo(organization=self, sort_order=order)
            logo.image.save(f"{stem}-{order}.webp", blob, save=False)
            logo.save()
            created.append(logo)
        return created
```

And add the model immediately after the `CEOrganization` class:

```python
class CEOrganizationLogo(models.Model):
    """One mark belonging to a CE accreditor.

    A body can require more than one image on an approved event's page, e.g. a
    sponsor logo alongside an approved-provider seal, so the logo is a set on
    the organization rather than a single field. Every event claiming the
    organization shows the whole set.
    """

    organization = models.ForeignKey(
        "events.CEOrganization", on_delete=models.CASCADE, related_name="logos",
    )
    image = models.ImageField(upload_to="ce-organizations/")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "pk")

    def __str__(self) -> str:
        return f"{self.organization.name} logo {self.sort_order}"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations events -n ce_organization_logos`
Expected: `events/migrations/0040_ce_organization_logos.py` containing a `CreateModel` for `CEOrganizationLogo` and a `RemoveField` removing `logo` from `ceorganization`.

- [ ] **Step 5: Hand-edit the migration to carry the existing logos across**

Open the generated file and insert a `RunPython` **between** the `CreateModel` and the `RemoveField` operations (order matters: the new table must exist and the old column must still be readable). Add at module level:

```python
def copy_logo_to_set(apps, schema_editor):
    """Move each organization's single logo onto a first CEOrganizationLogo row.

    Assigns the stored path rather than the file, so nothing is re-uploaded and
    the existing object keeps its key.
    """
    CEOrganization = apps.get_model("events", "CEOrganization")
    CEOrganizationLogo = apps.get_model("events", "CEOrganizationLogo")
    for org in CEOrganization.objects.exclude(logo="").exclude(logo=None):
        CEOrganizationLogo.objects.create(
            organization=org, image=org.logo.name, sort_order=1,
        )


def copy_set_to_logo(apps, schema_editor):
    """Reverse: put the first logo back on the organization."""
    CEOrganization = apps.get_model("events", "CEOrganization")
    CEOrganizationLogo = apps.get_model("events", "CEOrganizationLogo")
    for org in CEOrganization.objects.all():
        first = CEOrganizationLogo.objects.filter(
            organization=org,
        ).order_by("sort_order", "pk").first()
        if first is not None:
            org.logo = first.image.name
            org.save(update_fields=["logo"])
```

And the operation, placed between them:

```python
        migrations.RunPython(copy_logo_to_set, copy_set_to_logo),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce.py -q -n 0`
Expected: PASS.

- [ ] **Step 7: Verify the data migration against real rows**

The worktree's `db.sqlite3` holds a seeded organization with a logo from the
task #486 demo, so this is a real end-to-end check rather than a synthetic one.

Run: `uv run python manage.py migrate events`
Then run:

```
uv run python manage.py shell -c "from events.models import CEOrganization as C; print([(o.name, [l.image.name for l in o.logos.all()]) for o in C.objects.all()])"
```

Expected: each seeded organization prints exactly one logo path, and that path
is the same string the old `logo` column held (`ce-organizations/apa.webp` and
`ce-organizations/gppa.webp`). If the list is empty for an organization that
had a logo, the `RunPython` is on the wrong side of the `RemoveField`.

- [ ] **Step 8: Run the full events suite and lint**

Run: `uv run pytest events/ -q && uv run ruff check .`
Expected: `events/test_ce_display.py`, `events/test_ce_edit.py` and `events/test_ce_organization_add.py` **will fail** — they build organizations with `logo=`, and the templates still read `org.logo`. That is expected at this point; tasks 2 to 4 fix them. Note which fail so you can confirm they all go green by the end of task 4.

Lint must pass now.

- [ ] **Step 9: Commit**

```bash
git add events/models.py events/migrations/0040_ce_organization_logos.py events/test_ce.py
git commit -m "feat(events): a CE organization carries a set of logos (#486)"
```

---

### Task 2: Multi-file upload on the create form

**Files:**
- Modify: `events/ce_images.py` (add `MAX_LOGOS`)
- Modify: `events/forms.py` (`MultipleFileInput`, `MultipleFileField`, `clean_logo_files`, rework `CEOrganizationForm`)
- Modify: `events/views.py` (`ce_organization_add` passes the file list)
- Modify: `events/test_ce_organization_add.py`
- Test: `events/test_ce_organization_add.py` (append)

**Interfaces:**
- Consumes: `CEOrganization.add_logos(blobs)` from Task 1; `events.ce_images.normalize_logo`, `InvalidImage`, `MAX_UPLOAD_BYTES`.
- Produces:
  - `events.ce_images.MAX_LOGOS = 10`.
  - `events.forms.MultipleFileInput` / `events.forms.MultipleFileField` — a `FileField` whose `clean` returns a **list** of uploaded files.
  - `events.forms.clean_logo_files(files, *, existing=0) -> list[ContentFile]` — raises `forms.ValidationError`.
  - `events.forms.CEOrganizationForm` — `Meta.fields = ("name", "url", "statement")`, plus a `logos` `MultipleFileField`; `save(added_by=None, commit=True)` creates the organization **and** its logo rows.

- [ ] **Step 1: Write the failing tests**

In `events/test_ce_organization_add.py`, append:

```python
@pytest.mark.django_db
def test_several_logos_can_be_uploaded_at_once(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "APA", "logo": [_logo("a.png"), _logo("b.png", size=(4000, 1000))]},
    )
    assert response.status_code == 302
    org = CEOrganization.objects.get(name="APA")
    assert org.logos.count() == 2
    # Each one went through the same normalization as a single upload.
    second = Image.open(org.logos.all()[1].image.path)
    assert second.format == "WEBP"
    assert second.size == (800, 200)


@pytest.mark.django_db
def test_at_least_one_logo_is_required(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]), {"name": "Naked"},
    )
    assert response.status_code == 200
    assert not CEOrganization.objects.filter(name="Naked").exists()


@pytest.mark.django_db
def test_more_than_ten_logos_is_refused(client, event, faculty, settings, tmp_path):
    from events.ce_images import MAX_LOGOS

    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Greedy", "logo": [_logo(f"{i}.png") for i in range(MAX_LOGOS + 1)]},
    )
    assert response.status_code == 200
    assert b"at most 10 logos" in response.content
    assert not CEOrganization.objects.filter(name="Greedy").exists()
```

Then fix the three existing tests in that file, which assert on the old single field:

- `test_adding_an_organization_attaches_it_to_this_event` — unchanged, it never touches `logo` after the post.
- `test_the_stored_logo_is_normalized_webp` — change the final three lines from `org.logo.path` to the first row:

```python
    org = CEOrganization.objects.get(name="GPPA")
    img = Image.open(org.logos.first().image.path)
    assert img.format == "WEBP"
    assert img.size == (800, 200)
```

- `test_an_unreadable_logo_is_reported` and `test_a_duplicate_name_points_at_the_existing_entry` and `test_someone_who_cannot_edit_the_event_cannot_seed_the_library` — unchanged.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_organization_add.py -q -n 0`
Expected: FAIL — only one logo is stored, and there is no cap message.

- [ ] **Step 3: Add the cap constant**

In `events/ce_images.py`, below `MAX_UPLOAD_BYTES`:

```python
#: Most logos one organization may carry. Lives here beside the other upload
#: limits so every bound on a logo is in one file.
MAX_LOGOS = 10
```

- [ ] **Step 4: Add the multi-file field and the shared validator**

In `events/forms.py`, add above `CEOrganizationForm`:

```python
class MultipleFileInput(forms.ClearableFileInput):
    """A file input Django will read with ``getlist``.

    The template renders several inputs all named ``logo`` (the "Add another
    logo" button clones one), and this flag is what makes the field collect
    every one of them rather than the last.
    """

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """``FileField`` whose ``clean`` returns a list of uploaded files."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        # Handle "nothing uploaded" here rather than delegating: the base
        # class's required check never sees an empty *list*, so without this a
        # required field would silently accept a post with no files at all.
        items = [f for f in data if f] if isinstance(data, (list, tuple)) else (
            [data] if data else []
        )
        if not items:
            if self.required:
                raise forms.ValidationError(
                    self.error_messages["required"], code="required",
                )
            return []
        clean_one = super().clean
        return [clean_one(item, initial) for item in items]


def clean_logo_files(files, *, existing=0):
    """Normalize uploaded logos, or raise ``ValidationError`` saying why not.

    Shared by the create form and the per-organization page so the cap, the
    size limit, and the bounded-WebP rendering can't drift apart.
    """
    from .ce_images import MAX_LOGOS, MAX_UPLOAD_BYTES, InvalidImage, normalize_logo

    files = [f for f in files if f]
    if existing + len(files) > MAX_LOGOS:
        raise forms.ValidationError(
            f"An organization can carry at most {MAX_LOGOS} logos"
            + (f" and this one already has {existing}." if existing else ".")
        )
    blobs = []
    for f in files:
        if getattr(f, "size", 0) > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(f"{f.name} is too large (8 MB max).")
        try:
            blobs.append(normalize_logo(f))
        except InvalidImage as exc:
            raise forms.ValidationError(f"{f.name}: {exc}") from exc
    return blobs
```

- [ ] **Step 5: Rework the create form**

Replace the whole `CEOrganizationForm` class in `events/forms.py` with:

```python
class CEOrganizationForm(forms.ModelForm):
    """Add an accrediting body to the shared library, from an event page.

    The library is not curated, so the guard rails are here: a case-insensitive
    name check that points at the existing entry rather than minting a second
    one, and logo normalization so nobody's 4000px PNG lands on an event page.
    """

    logos = MultipleFileField(
        label="Logo", required=True,
        error_messages={"required": "Add at least one logo."},
    )

    class Meta:
        model = CEOrganization
        fields = ("name", "url", "statement")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "url": forms.URLInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "statement": forms.Textarea(
                attrs={"class": "textarea textarea-bordered w-full", "rows": 3},
            ),
        }

    def clean_name(self):
        name = (self.cleaned_data["name"] or "").strip()
        existing = CEOrganization.objects.filter(name__iexact=name).first()
        if existing is not None:
            raise forms.ValidationError(
                f"{existing.name} is already listed. Tick it in the list above "
                "instead of adding it again."
            )
        return name

    def clean_logos(self):
        return clean_logo_files(self.cleaned_data.get("logos") or [])

    def save(self, added_by=None, commit=True):
        org = super().save(commit=False)
        org.added_by = added_by
        org.save()
        org.add_logos(self.cleaned_data["logos"])
        return org
```

Note the behaviour change: `save()` always writes to the database, because the
logo rows need the organization's primary key. `commit` is kept in the
signature for ModelForm compatibility and is unused.

- [ ] **Step 6: Feed the view the file list**

In `events/views.py`, in `ce_organization_add`, replace the form construction:

```python
    org_form = CEOrganizationForm(request.POST, request.FILES)
```

with a version that hands the field every uploaded file:

```python
    from django.utils.datastructures import MultiValueDict

    org_form = CEOrganizationForm(
        request.POST, MultiValueDict({"logos": request.FILES.getlist("logo")}),
    )
```

The inputs are named `logo` in the markup (a set of them) and the form field is
`logos`, so the list is mapped across explicitly rather than relying on the
names matching. It must be a `MultiValueDict`, not a plain `dict`: the widget
reads multiple files with `files.getlist(name)`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_organization_add.py -q -n 0`
Expected: PASS, 8 tests.

- [ ] **Step 8: Lint**

Run: `uv run ruff check .`
Expected: clean. (The full suite still has the display/edit failures from Task 1; Task 3 fixes them.)

- [ ] **Step 9: Commit**

```bash
git add events/ce_images.py events/forms.py events/views.py events/test_ce_organization_add.py
git commit -m "feat(events): upload several CE logos at once (#486)"
```

---

### Task 3: Render the whole set, and the Add-another-logo control

**Files:**
- Create: `events/templates/events/_ce_logo_inputs.html`
- Modify: `events/templates/events/_ce_credits.html`
- Modify: `events/templates/events/event_edit.html`
- Modify: `events/views.py` (`_ce_edit_context` prefetch, `max_new_logos`)
- Modify: `events/test_ce_display.py`, `events/test_ce_edit.py`

**Interfaces:**
- Consumes: `CEOrganization.logos` from Task 1; `MAX_LOGOS` from Task 2.
- Produces: the partial `events/_ce_logo_inputs.html`, expecting `max_new` (int) in context; the edit-page context key `max_new_logos`.

- [ ] **Step 1: Write the failing tests**

In `events/test_ce_display.py`, replace the `logo` fixture and add a set test. The fixture becomes a helper that makes a real PNG (the 1x1 byte-blob is fine for markup, but `add_logos` wants something Pillow can open):

```python
def _blob():
    """A WebP blob shaped like normalize_logo() output."""
    import io

    from django.core.files.base import ContentFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())
```

Change `test_ce_panel_shows_logo_statement_and_note` to build the organization
without `logo=` and call `add_logos`:

```python
@pytest.mark.django_db
def test_ce_panel_shows_logo_statement_and_note(client, event, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="American Psychological Association",
        url="https://www.apa.org/",
        statement="LSP maintains responsibility for this program and its content.",
    )
    org.add_logos([_blob()])
    event.offers_ce = True
    event.ce_credits = Decimal("2.00")
    event.ce_credits_basis = CECreditBasis.PER_MEETING
    event.ce_note = "Full attendance is required for credit."
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Approved for 2 CE credits per meeting." in body
    assert 'alt="American Psychological Association logo"' in body
    assert "https://www.apa.org/" in body
    assert "LSP maintains responsibility for this program and its content." in body
    assert "Full attendance is required for credit." in body
```

Delete the old `logo` fixture (the 1x1 `SimpleUploadedFile`) and its
`SimpleUploadedFile` import if nothing else uses it. Then append:

```python
@pytest.mark.django_db
def test_every_logo_in_the_set_is_shown(client, event, settings, tmp_path):
    """A body requiring a sponsor mark and a provider seal gets both on every
    event that claims it."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="APA")
    org.add_logos([_blob(), _blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert body.count('alt="APA logo"') == 3


@pytest.mark.django_db
def test_an_organization_with_no_logos_renders_without_error(client, event):
    """Defensive: admin can delete the last row even though the UI refuses to."""
    org = CEOrganization.objects.create(name="Logoless")
    org.statement = "Still has something to say."
    org.save()
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    response = client.get(reverse("events:detail", args=[event.slug]))
    assert response.status_code == 200
    assert b"Still has something to say." in response.content
```

In `events/test_ce_edit.py`, the `org` fixture creates `CEOrganization.objects.create(name="GPPA")` with no logo, which still works. Append:

```python
@pytest.mark.django_db
def test_edit_page_offers_the_add_another_logo_control(client, event, faculty):
    client.force_login(faculty)
    body = client.get(reverse("events:edit", args=[event.slug])).content.decode()
    assert "Add another logo" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_display.py events/test_ce_edit.py -q -n 0`
Expected: FAIL — the templates still read `org.logo`, and there is no add-another control.

- [ ] **Step 3: Write the logo-inputs partial**

Create `events/templates/events/_ce_logo_inputs.html`:

```html
{% comment %}Logo file inputs plus an "Add another logo" button (task #486).

Every input is named "logo"; the view reads request.FILES.getlist("logo") and
hands the list to the form's `logos` MultipleFileField. Expects: max_new (how
many more this organization may take). With JavaScript off you still get one
working input, so the form degrades rather than breaks.{% endcomment %}
<div class="space-y-2" data-logo-inputs data-max="{{ max_new }}">
  <div data-logo-row>
    <input type="file" name="logo" accept="image/*"
           class="file-input file-input-sm w-full">
  </div>
  <button type="button" class="btn btn-ghost btn-xs" data-add-logo>
    + Add another logo
  </button>
</div>
<script>
  if (!window.__ceLogoInputs) {
    window.__ceLogoInputs = true;
    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-add-logo]");
      if (!btn) return;
      var box = btn.closest("[data-logo-inputs]");
      var rows = box.querySelectorAll("[data-logo-row]");
      var max = parseInt(box.getAttribute("data-max"), 10) || 1;
      if (rows.length >= max) return;
      var row = rows[rows.length - 1].cloneNode(true);
      row.querySelector("input").value = "";
      rows[rows.length - 1].after(row);
      if (rows.length + 1 >= max) btn.setAttribute("hidden", "hidden");
    });
  }
</script>
```

- [ ] **Step 4: Render the set in the public panel**

In `events/templates/events/_ce_credits.html`, replace the logo block. The
current `{% if org.logo %}` guard becomes a loop over the set:

```html
    {% for org in orgs %}
    {% for logo in org.logos.all %}
    <span class="inline-flex items-center rounded-lg border border-base-300/60 bg-white p-2">
      {% if org.url %}<a href="{{ org.url }}" target="_blank" rel="noopener">{% endif %}
      <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
           class="max-h-12 max-w-36 object-contain">
      {% if org.url %}</a>{% endif %}
    </span>
    {% endfor %}
    {% endfor %}
```

- [ ] **Step 5: Render the set on the edit page and add the control**

In `events/templates/events/event_edit.html`, in the organization checkbox
list, replace the single-chip block:

```html
          {% if org.logo %}
          <span class="inline-flex items-center rounded border border-base-300/60 bg-white p-1.5">
            <img src="{{ org.logo.url }}" alt="{{ org.name }} logo"
                 class="max-h-8 max-w-28 object-contain">
          </span>
          {% endif %}
```

with:

```html
          {% for logo in org.logos.all %}
          <span class="inline-flex items-center rounded border border-base-300/60 bg-white p-1.5">
            <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
                 class="max-h-8 max-w-28 object-contain">
          </span>
          {% endfor %}
```

Then in the add-organization form, replace the single logo input block:

```html
      <div class="space-y-1">
        <label for="id_logo" class="block text-xs text-base-content/60">Logo</label>
        <input type="file" name="logo" id="id_logo" accept="image/*" required
               class="file-input file-input-bordered file-input-sm w-full">
        {% if f.logo.errors %}<p class="text-xs text-error">{{ f.logo.errors|join:", " }}</p>{% endif %}
      </div>
```

with:

```html
      <div class="space-y-1">
        <span class="block text-xs text-base-content/60">Logos</span>
        {% include "events/_ce_logo_inputs.html" with max_new=max_new_logos %}
        {% if f.logos.errors %}<p class="text-xs text-error">{{ f.logos.errors|join:", " }}</p>{% endif %}
      </div>
```

- [ ] **Step 6: Supply `max_new_logos` and prefetch the sets**

In `events/views.py`, update `_ce_edit_context`:

```python
def _ce_edit_context(form):
    """Organization checkboxes for the edit form.

    Rendered by hand rather than through the widget so each option can show its
    logos. ``BoundField.value()`` gives the *submitted* selection when the form
    is bound, so a failed POST re-renders with the user's ticks intact.
    """
    from .ce_images import MAX_LOGOS
    from .models import CEOrganization

    return {
        "ce_organizations": CEOrganization.objects.prefetch_related("logos"),
        "selected_ce_values": [str(v) for v in (form["ce_organizations"].value() or [])],
        "max_new_logos": MAX_LOGOS,
    }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_display.py events/test_ce_edit.py -q -n 0`
Expected: PASS.

- [ ] **Step 8: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: everything green, including the tests that were failing after Task 1.

- [ ] **Step 9: Commit**

```bash
git add events/templates/events/_ce_logo_inputs.html events/templates/events/_ce_credits.html events/templates/events/event_edit.html events/views.py events/test_ce_display.py events/test_ce_edit.py
git commit -m "feat(events): show a CE organization's whole logo set (#486)"
```

---

### Task 4: The per-organization page

**Files:**
- Modify: `events/forms.py` (append `CEOrganizationDetailsForm`)
- Modify: `events/views.py` (append `ce_organization_edit`)
- Modify: `events/urls.py`
- Create: `events/templates/events/ce_organization_edit.html`
- Modify: `events/templates/events/event_edit.html` (a Manage link per organization row)
- Test: `events/test_ce_organization_edit.py`

**Interfaces:**
- Consumes: `clean_logo_files`, `MultipleFileField`, `MAX_LOGOS` from Task 2; `CEOrganization.add_logos` from Task 1; the `events/_ce_logo_inputs.html` partial from Task 3.
- Produces: `events.forms.CEOrganizationDetailsForm`; the URL name `events:ce_organization_edit` taking `slug` and `pk`.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_organization_edit.py`:

```python
"""The per-organization page: manage its logo set, URL, and statement (#486)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.ce_images import MAX_LOGOS
from events.models import CEOrganization, CEOrganizationLogo, Event


def _upload(name="logo.png", size=(400, 200)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGBA", size, (10, 20, 30, 255)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _blob() -> ContentFile:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-orgedit@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider-orgedit@x.test")


@pytest.fixture
def org(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    o = CEOrganization.objects.create(name="APA", url="https://www.apa.org/")
    o.add_logos([_blob()])
    return o


def _url(event, org):
    return reverse("events:ce_organization_edit", args=[event.slug, org.pk])


@pytest.mark.django_db
def test_the_page_lists_the_logos_and_omits_a_name_field(client, event, org, faculty):
    """The name is the case-insensitive dedup key and renaming ripples through
    every event, so it stays a Django admin action."""
    client.force_login(faculty)
    body = client.get(_url(event, org)).content.decode()
    assert "APA" in body
    assert 'name="url"' in body
    assert 'name="statement"' in body
    assert 'name="name"' not in body


@pytest.mark.django_db
def test_logos_can_be_added(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": org.url, "statement": "", "logo": [_upload("b.png"), _upload("c.png")],
    })
    assert response.status_code == 302
    assert org.logos.count() == 3


@pytest.mark.django_db
def test_the_url_and_statement_can_be_edited(client, event, org, faculty):
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": "https://apa.example/", "statement": "Approved provider.",
    })
    assert response.status_code == 302
    org.refresh_from_db()
    assert org.url == "https://apa.example/"
    assert org.statement == "Approved provider."


@pytest.mark.django_db
def test_a_logo_can_be_removed(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org.add_logos([_blob()])
    extra = org.logos.last()
    client.force_login(faculty)
    response = client.post(_url(event, org), {"action": "remove", "logo_id": extra.pk})
    assert response.status_code == 302
    assert org.logos.count() == 1
    assert not CEOrganizationLogo.objects.filter(pk=extra.pk).exists()


@pytest.mark.django_db
def test_the_last_logo_cannot_be_removed(client, event, org, faculty):
    """An organization with no logos renders as a statement with no mark, which
    nobody sets out to create. Replace is add-then-remove."""
    only = org.logos.first()
    client.force_login(faculty)
    response = client.post(
        _url(event, org), {"action": "remove", "logo_id": only.pk}, follow=True,
    )
    assert org.logos.count() == 1
    assert b"add the replacement first" in response.content


@pytest.mark.django_db
def test_the_cap_counts_logos_already_there(client, event, org, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org.add_logos([_blob() for _ in range(MAX_LOGOS - 1)])   # now at the cap
    client.force_login(faculty)
    response = client.post(_url(event, org), {
        "url": "", "statement": "", "logo": [_upload("over.png")],
    })
    assert response.status_code == 200
    assert b"at most 10 logos" in response.content
    assert org.logos.count() == MAX_LOGOS


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_is_refused(client, event, org, outsider):
    client.force_login(outsider)
    assert client.get(_url(event, org)).status_code == 403
    assert client.post(_url(event, org), {"url": "", "statement": ""}).status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_organization_edit.py -q -n 0`
Expected: FAIL, `NoReverseMatch: 'ce_organization_edit' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the details form**

Append to `events/forms.py`:

```python
class CEOrganizationDetailsForm(forms.ModelForm):
    """Edit an existing accreditor: its logo set, site, and required wording.

    No name field on purpose. The name is the case-insensitive dedup key, and a
    rename ripples through every event claiming the organization, so renaming
    stays a Django admin action.
    """

    logos = MultipleFileField(label="Add logos", required=False)

    class Meta:
        model = CEOrganization
        fields = ("url", "statement")
        widgets = {
            "url": forms.URLInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "statement": forms.Textarea(
                attrs={"class": "textarea textarea-bordered w-full", "rows": 3},
            ),
        }

    def clean_logos(self):
        return clean_logo_files(
            self.cleaned_data.get("logos") or [],
            existing=self.instance.logos.count(),
        )

    def save(self, commit=True):
        org = super().save(commit=commit)
        org.add_logos(self.cleaned_data.get("logos") or [])
        return org
```

- [ ] **Step 4: Add the view**

In `events/views.py`, append after `ce_organization_add`:

```python
@login_required
def ce_organization_edit(request, slug: str, pk: int):
    """Manage a CE organization's logo set, site, and required wording.

    The event in the path is provenance for the permission check and the back
    link only. The organization is shared, so edits here land on every event
    that claims it, which the page says in as many words.
    """
    from .ce_images import MAX_LOGOS
    from .forms import CEOrganizationDetailsForm
    from .models import CEOrganization

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to edit this event.")
    org = get_object_or_404(CEOrganization, pk=pk)

    if request.method == "POST" and request.POST.get("action") == "remove":
        if org.logos.count() <= 1:
            messages.error(
                request,
                "An organization needs at least one logo. To swap this one out, "
                "add the replacement first, then remove this.",
            )
        else:
            org.logos.filter(pk=request.POST.get("logo_id")).delete()
            messages.success(request, "Logo removed.")
        return redirect("events:ce_organization_edit", slug=event.slug, pk=org.pk)

    if request.method == "POST":
        from django.utils.datastructures import MultiValueDict

        form = CEOrganizationDetailsForm(
            request.POST,
            MultiValueDict({"logos": request.FILES.getlist("logo")}),
            instance=org,
        )
        if form.is_valid():
            form.save()
            messages.success(request, f"Saved {org.name}.")
            return redirect("events:edit", slug=event.slug)
    else:
        form = CEOrganizationDetailsForm(instance=org)

    return render(request, "events/ce_organization_edit.html", {
        "event": event, "organization": org, "form": form,
        "logos": list(org.logos.all()),
        "max_new_logos": max(0, MAX_LOGOS - org.logos.count()),
    })
```

- [ ] **Step 5: Wire the URL**

In `events/urls.py`, after the `ce_organization_add` entry:

```python
    path("<slug:slug>/ce-organizations/<int:pk>/",
         views.ce_organization_edit, name="ce_organization_edit"),
```

- [ ] **Step 6: Write the page template**

Create `events/templates/events/ce_organization_edit.html`:

```html
{% extends "core/base.html" %}
{% block title %}{{ organization.name }} · CE organization · LSP{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto space-y-6">

  <header class="space-y-1">
    <h1 class="font-serif text-3xl text-base-content">{{ organization.name }}</h1>
    <p class="text-sm">
      <a href="{% url 'events:edit' event.slug %}" class="link link-hover text-base-content/70">← Back to {{ event.title }}</a>
    </p>
  </header>

  <div class="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-base-content/80">
    This organization is shared across the whole site. Changes here appear on
    every event approved by it, not just this one.
  </div>

  <section class="space-y-3">
    <h2 class="font-serif text-lg text-base-content">Logos</h2>
    {% if logos %}
    <ul class="space-y-2">
      {% for logo in logos %}
      <li class="flex items-center gap-3">
        <span class="inline-flex items-center rounded border border-base-300/60 bg-white p-1.5">
          <img src="{{ logo.image.url }}" alt="{{ organization.name }} logo"
               class="max-h-12 max-w-36 object-contain">
        </span>
        <form method="post" class="ml-auto">
          {% csrf_token %}
          <input type="hidden" name="action" value="remove">
          <input type="hidden" name="logo_id" value="{{ logo.pk }}">
          <button class="btn btn-ghost btn-xs text-error">Remove</button>
        </form>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-sm text-base-content/50">No logos yet.</p>
    {% endif %}
  </section>

  <form method="post" enctype="multipart/form-data" class="space-y-4">
    {% csrf_token %}

    <div class="space-y-1">
      <span class="block text-xs text-base-content/60">
        Add logos{% if max_new_logos %} (room for {{ max_new_logos }} more){% endif %}
      </span>
      {% if max_new_logos %}
      {% include "events/_ce_logo_inputs.html" with max_new=max_new_logos %}
      {% else %}
      <p class="text-xs text-base-content/50">This organization is at the limit of 10 logos.</p>
      {% endif %}
      {% if form.logos.errors %}<p class="text-xs text-error">{{ form.logos.errors|join:", " }}</p>{% endif %}
    </div>

    <div class="space-y-1">
      <label for="id_url" class="block text-xs text-base-content/60">Website</label>
      {{ form.url }}
      <p class="text-xs text-base-content/60">Links the logos when set.</p>
      {% if form.url.errors %}<p class="text-xs text-error">{{ form.url.errors|join:", " }}</p>{% endif %}
    </div>

    <div class="space-y-1">
      <label for="id_statement" class="block text-xs text-base-content/60">Required approval language</label>
      {{ form.statement }}
      <p class="text-xs text-base-content/60">Wording this body requires on approved events. Shown under its logos on every event that claims it.</p>
      {% if form.statement.errors %}<p class="text-xs text-error">{{ form.statement.errors|join:", " }}</p>{% endif %}
    </div>

    <button type="submit" class="btn btn-primary">Save</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Link it from each organization row**

In `events/templates/events/event_edit.html`, the organization row after Task 3
reads (lines 139-151):

```html
        {% for org in ce_organizations %}
        <label class="flex cursor-pointer items-center gap-3">
          <input type="checkbox" name="ce_organizations" value="{{ org.pk }}"
                 class="checkbox checkbox-sm"
                 {% if org.pk|stringformat:"s" in selected_ce_values %}checked{% endif %}>
          {% for logo in org.logos.all %}
          <span class="inline-flex items-center rounded border border-base-300/60 bg-white p-1.5">
            <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
                 class="max-h-8 max-w-28 object-contain">
          </span>
          {% endfor %}
          <span class="text-sm text-base-content">{{ org.name }}</span>
        </label>
```

Replace that whole block with this. The link must sit **outside** the
`<label>`, because a click anywhere inside a label toggles its checkbox:

```html
        {% for org in ce_organizations %}
        <div class="flex items-center gap-3">
          <label class="flex flex-1 cursor-pointer items-center gap-3">
            <input type="checkbox" name="ce_organizations" value="{{ org.pk }}"
                   class="checkbox checkbox-sm"
                   {% if org.pk|stringformat:"s" in selected_ce_values %}checked{% endif %}>
            {% for logo in org.logos.all %}
            <span class="inline-flex items-center rounded border border-base-300/60 bg-white p-1.5">
              <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
                   class="max-h-8 max-w-28 object-contain">
            </span>
            {% endfor %}
            <span class="text-sm text-base-content">{{ org.name }}</span>
          </label>
          <a href="{% url 'events:ce_organization_edit' event.slug org.pk %}"
             class="link link-hover text-xs text-base-content/50">Manage logos</a>
        </div>
```

Leave the `{% empty %}` clause and `{% endfor %}` that follow untouched.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_organization_edit.py -q -n 0`
Expected: PASS, 7 tests.

- [ ] **Step 9: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green.

- [ ] **Step 10: Rebuild CSS and look at both pages**

Run: `npm run build:css`

Then start the server (`uv run python manage.py runserver 8912 --noreload`) and check, on the seeded `ce-demo-day` event:

- the public page shows every logo in each organization's set;
- the edit page's organization rows show their sets and a working "Manage logos" link;
- "Add another logo" adds a second file input and stops at the cap;
- the per-organization page removes a logo, and refuses to remove the last one.

Confirm the logo chips stay legible in **both** themes (the toggle is in the header).

- [ ] **Step 11: Commit**

```bash
git add events/forms.py events/views.py events/urls.py events/templates/events/ce_organization_edit.html events/templates/events/event_edit.html events/test_ce_organization_edit.py
git commit -m "feat(events): manage a CE organization's logos, site, and wording (#486)"
```

---

## Notes for the reviewer

- **Task 1 deliberately leaves the suite red.** Removing `CEOrganization.logo` breaks the display and create tests that still reference it; tasks 2 and 3 repair them. Only lint is required to pass at the end of Task 1.
- **`CEOrganizationForm.save()` now always hits the database**, because logo rows need the organization's primary key. `commit` stays in the signature for ModelForm compatibility and is ignored.
- **The inputs are named `logo` while the form field is `logos`.** The view maps `request.FILES.getlist("logo")` onto `{"logos": ...}` explicitly. Keeping the input name singular means the existing single-logo markup and any bookmarked form still post something the view understands.
- **Not built, per the spec:** reordering logos, renaming an organization outside Django admin, per-event selection of which logos to show, and deleting an organization from the member-facing UI.
