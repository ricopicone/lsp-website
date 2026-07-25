# Works Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Structured Chicago-style citation data + rendering for external publications, random-default ordering with explicit sort options, and a grid/list toggle on `/works/`, per `docs/superpowers/specs/2026-07-24-works-polish-design.md` (task #465).

**Architecture:** Additive fields on `works.Work` + a pure-function citation renderer (`works/citation.py`) consumed by the detail page, cards, and new list rows. The index view gains `?sort=` and `?view=` (cookie-remembered) handling. A curated JSON mapping applied by an idempotent `backfill_citations` management command migrates existing prod entries.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5 templates, `{% querystring %}` template tag (Django ≥5.1).

## Global Constraints

- Member-facing site copy uses commas instead of em dashes (project convention).
- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content/60`, …), never hardcoded colors.
- Tailwind classes set in Python must also appear in some .html (Tailwind scans templates only).
- `Work.Meta.ordering` must NOT change (group Work tabs and other consumers rely on it).
- All member-entered text is escaped in rendered citations; only our own `<i>`/`<a>` markup is safe.
- Run tests with `uv run pytest works/ -x -q`; lint with `uv run ruff check works/`.
- Commit after each task; messages end with `(task #465)` and the Claude trailer.

---

### Task 1: Model fields + migration + admin

**Files:**
- Modify: `works/models.py` (Work — after `publication_date`, ~line 98)
- Modify: `works/admin.py` (Content fieldset, search_fields)
- Create: `works/migrations/0013_work_structured_citation.py` (via makemigrations)
- Test: `works/test_polish.py` (new file)

**Interfaces:**
- Produces: `Work.ExternalType` TextChoices (`ARTICLE="article"`, `BOOK="book"`, `CHAPTER="chapter"`, `EDITED_VOLUME="edited_volume"`, `OTHER="other"`); fields `external_type` (blank ok), `container_title`, `publisher`, `edition`, `volume`, `issue`, `pages`, `editors`, `translators`, `doi`, `isbn` (all `blank=True`); helper `Work.has_structured_citation` property; `Work.doi_url` property.

- [ ] **Step 1: Failing test** (`works/test_polish.py`):

```python
import pytest

from works.models import Work

pytestmark = pytest.mark.django_db


def make_work(**kw):
    kw.setdefault("title", "On the Gaze")
    kw.setdefault("slug", kw["title"].lower().replace(" ", "-"))
    kw.setdefault("kind", Work.Kind.EXTERNAL)
    return Work.objects.create(**kw)


class TestStructuredCitationFields:
    def test_fields_default_blank_and_flag_off(self):
        w = make_work()
        assert w.external_type == ""
        assert w.has_structured_citation is False

    def test_flag_on_when_any_field_set(self):
        w = make_work(container_title="Psychoanalytic Review")
        assert w.has_structured_citation is True

    def test_doi_url(self):
        w = make_work(doi="10.1234/xyz")
        assert w.doi_url == "https://doi.org/10.1234/xyz"
        assert make_work(title="No doi", slug="no-doi").doi_url == ""
```

- [ ] **Step 2:** `uv run pytest works/test_polish.py -x -q` → FAIL (no such field).
- [ ] **Step 3: Implement** — in `works/models.py`, inside `Work` add after the `Visibility` choices:

```python
    class ExternalType(models.TextChoices):
        ARTICLE       = "article",       _("Journal article")
        BOOK          = "book",          _("Book")
        CHAPTER       = "chapter",       _("Book chapter")
        EDITED_VOLUME = "edited_volume", _("Edited volume")
        OTHER         = "other",         _("Other")
```

and after `publication_date`:

```python
    # ---- Structured citation (external publications; all optional) ----
    external_type = models.CharField(
        max_length=16, choices=ExternalType.choices, blank=True, default="",
        verbose_name="publication type",
    )
    container_title = models.CharField(
        max_length=255, blank=True,
        help_text="Journal name, or the book's title for a chapter.",
    )
    publisher = models.CharField(max_length=255, blank=True)
    edition = models.CharField(max_length=50, blank=True, help_text='E.g. "2nd ed."')
    volume = models.CharField(max_length=50, blank=True)
    issue = models.CharField(max_length=50, blank=True)
    pages = models.CharField(max_length=50, blank=True, help_text='E.g. "33–58".')
    editors = models.CharField(
        max_length=255, blank=True, help_text='Names only, e.g. "Jane Doe and John Roe".',
    )
    translators = models.CharField(max_length=255, blank=True, help_text="Names only.")
    doi = models.CharField(
        max_length=255, blank=True, verbose_name="DOI",
        help_text='Bare DOI, e.g. "10.1234/xyz". A pasted doi.org URL is accepted.',
    )
    isbn = models.CharField(max_length=32, blank=True, verbose_name="ISBN")
```

plus display helpers next to `abstract_html`:

```python
    STRUCTURED_CITATION_FIELDS = (
        "external_type", "container_title", "publisher", "edition", "volume",
        "issue", "pages", "editors", "translators", "doi", "isbn",
    )

    @property
    def has_structured_citation(self) -> bool:
        return any(getattr(self, f) for f in self.STRUCTURED_CITATION_FIELDS)

    @property
    def doi_url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""
```

- [ ] **Step 4:** `uv run python manage.py makemigrations works` (expect `0013_…`), rerun test → PASS.
- [ ] **Step 5: Admin** — Content fieldset becomes `("abstract", "publication_info", "url", "publication_date", "external_type", "container_title", "publisher", "edition", "volume", "issue", "pages", "editors", "translators", "doi", "isbn")`; append `"container_title", "publisher", "doi", "isbn"` to `search_fields`.
- [ ] **Step 6:** Full `uv run pytest works/ -q` + `uv run ruff check works/` green; commit `feat(works): structured citation fields on Work (task #465)`.

### Task 2: Chicago citation renderer

**Files:**
- Create: `works/citation.py`
- Create: `works/test_citation.py`

**Interfaces:**
- Consumes: Task 1 fields; `WorkAuthor` byline order; `Work.external_authors`; `Work.publication_date`.
- Produces: `citation_html(work) -> SafeString` (full Chicago citation), `citation_text(work) -> str` (plain-text twin for copy), `source_html(work) -> SafeString` (citation minus authors + title, for the detail header and cards; empty string when nothing to show). All escape member text; italics via `<i>`.

- [ ] **Step 1: Failing tests** (`works/test_citation.py`) — representative set:

```python
import datetime

import pytest

from works.citation import citation_html, citation_text, source_html
from works.models import Work, WorkAuthor

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        email="s@example.org", password="x", first_name="Stephanie", last_name="Swales",
    )


def make_work(author=None, **kw):
    kw.setdefault("title", "Surplus Enjoyment")
    kw.setdefault("slug", kw["title"].lower().replace(" ", "-"))
    kw.setdefault("kind", Work.Kind.EXTERNAL)
    w = Work.objects.create(**kw)
    if author:
        WorkAuthor.objects.create(work=w, user=author, display_order=0)
    return w


def test_article(author):
    w = make_work(
        author=author,
        external_type=Work.ExternalType.ARTICLE,
        container_title="Psychoanalytic Review",
        volume="12", issue="2", pages="33–58",
        publication_date=datetime.date(2024, 5, 1),
        doi="10.1234/xyz",
    )
    text = citation_text(w)
    assert text == (
        "Swales, Stephanie. 2024. “Surplus Enjoyment.” "
        "Psychoanalytic Review 12 (2): 33–58. https://doi.org/10.1234/xyz."
    )
    html = citation_html(w)
    assert "<i>Psychoanalytic Review</i>" in html
    assert 'href="https://doi.org/10.1234/xyz"' in html


def test_book(author):
    w = make_work(
        author=author, title="Book of Drives", slug="bod",
        external_type=Work.ExternalType.BOOK, publisher="Routledge",
        edition="2nd ed.", publication_date=datetime.date(2023, 1, 1),
    )
    assert citation_text(w) == "Swales, Stephanie. 2023. Book of Drives. 2nd ed. Routledge."
    assert "<i>Book of Drives</i>" in citation_html(w)


def test_chapter(author):
    w = make_work(
        author=author, title="On Lack", slug="on-lack",
        external_type=Work.ExternalType.CHAPTER,
        container_title="Reading Lacan", editors="Derek Hook", pages="101–120",
        publisher="Palgrave", publication_date=datetime.date(2022, 1, 1),
    )
    assert citation_text(w) == (
        "Swales, Stephanie. 2022. “On Lack.” In Reading Lacan, "
        "edited by Derek Hook, 101–120. Palgrave."
    )


def test_edited_volume_marks_eds(author):
    w = make_work(
        author=author, title="Lacan Reader", slug="lr",
        external_type=Work.ExternalType.EDITED_VOLUME, publisher="Routledge",
        publication_date=datetime.date(2021, 1, 1),
    )
    assert citation_text(w).startswith("Swales, Stephanie, ed. 2021.")


def test_two_authors_and_external(author, django_user_model):
    other = django_user_model.objects.create_user(
        email="d@example.org", password="x", first_name="Derek", last_name="Hook",
    )
    w = make_work(author=author, external_authors="Jane Doe")
    WorkAuthor.objects.create(work=w, user=other, display_order=1)
    assert citation_text(w).startswith("Swales, Stephanie, Derek Hook, and Jane Doe.")


def test_no_date_renders_nd(author):
    w = make_work(author=author)
    assert " n.d. " in " " + citation_text(w) + " "


def test_escaping():
    w = make_work(title="A <script> Title", container_title="J<b>X")
    assert "<script>" not in citation_html(w)
    assert "<b>" not in citation_html(w).replace("<i>", "").replace("</i>", "")


def test_source_html_omits_authors_and_title(author):
    w = make_work(
        author=author, external_type=Work.ExternalType.ARTICLE,
        container_title="Psychoanalytic Review", volume="12", pages="33–58",
        publication_date=datetime.date(2024, 5, 1),
    )
    s = source_html(w)
    assert "Swales" not in s and "Surplus" not in s
    assert "<i>Psychoanalytic Review</i>" in s

def test_source_html_empty_without_data():
    assert source_html(make_work(title="Bare", slug="bare")) == ""
```

- [ ] **Step 2:** Run → FAIL (module missing).
- [ ] **Step 3: Implement** `works/citation.py`:

```python
"""Chicago author-date citation rendering for external-publication Works.

Pure functions over a ``Work``: build an ordered list of *segments*
(text, italic?, href?) and render them twice — as escaped HTML (site
display) and as plain text (the copy-to-clipboard string). Degrades
gracefully: absent fields are skipped, punctuation never dangles.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe


@dataclass
class Seg:
    text: str
    italic: bool = False
    href: str = ""


def _authors(work) -> str:
    """Chicago byline: first author inverted, rest natural, joined with and."""
    names: list[str] = []
    for i, wa in enumerate(
        work.authorships.select_related("user").order_by("display_order")
    ):
        u = wa.user
        full = f"{u.first_name} {u.last_name}".strip()
        if i == 0 and u.last_name:
            names.append(f"{u.last_name}, {u.first_name}".strip().strip(","))
        elif full:
            names.append(full)
    if work.external_authors:
        names.extend(
            t.strip() for t in work.external_authors.split(",") if t.strip()
        )
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _year(work) -> str:
    return str(work.publication_date.year) if work.publication_date else "n.d."


def _vol_issue_pages(work) -> str:
    """"12 (2): 33–58" with any subset present."""
    vi = work.volume
    if work.issue:
        vi = f"{vi} ({work.issue})" if vi else f"({work.issue})"
    if work.pages:
        return f"{vi}: {work.pages}" if vi else work.pages
    return vi


def _sentence(segs: list[Seg]) -> list[Seg]:
    """Terminate the last segment with a period unless already punctuated."""
    if segs and segs[-1].text and segs[-1].text[-1] not in ".!?":
        segs[-1] = Seg(segs[-1].text + ".", segs[-1].italic, segs[-1].href)
    return segs


def _body_segments(work) -> list[Seg]:
    """Everything after authors+year+title, per publication type."""
    T = type(work).ExternalType
    kind = work.external_type
    segs: list[Seg] = []
    vip = _vol_issue_pages(work)

    if kind == T.ARTICLE or (not kind and work.container_title and not work.publisher):
        if work.container_title:
            segs.append(Seg(work.container_title, italic=True))
        if vip:
            segs.append(Seg(vip))
        return _sentence(segs)

    if kind == T.CHAPTER:
        if work.container_title:
            segs.append(Seg("In "))
            segs.append(Seg(work.container_title, italic=True))
        if work.editors:
            segs.append(Seg(f", edited by {work.editors}"))
        if work.translators:
            segs.append(Seg(f", translated by {work.translators}"))
        if work.pages:
            segs.append(Seg(f", {work.pages}"))
        _sentence(segs)
        if work.publisher:
            segs.append(Seg(" "))
            segs.extend(_sentence([Seg(work.publisher)]))
        return segs

    # book / edited volume / other: container (other), edition, eds/trans, publisher
    if work.container_title:
        segs.extend(_sentence([Seg(work.container_title, italic=True)]) + [Seg(" ")])
        if vip:
            segs.extend(_sentence([Seg(vip)]) + [Seg(" ")])
    if work.editors and kind != T.EDITED_VOLUME:
        segs.extend(_sentence([Seg(f"Edited by {work.editors}")]) + [Seg(" ")])
    if work.translators:
        segs.extend(_sentence([Seg(f"Translated by {work.translators}")]) + [Seg(" ")])
    if work.edition:
        segs.extend(_sentence([Seg(work.edition)]) + [Seg(" ")])
    if work.publisher:
        segs.extend(_sentence([Seg(work.publisher)]))
    while segs and not segs[-1].text.strip():
        segs.pop()
    return segs


def _title_segments(work) -> list[Seg]:
    T = type(work).ExternalType
    quoted = work.external_type in (T.ARTICLE, T.CHAPTER) or (
        not work.external_type and work.container_title
    )
    if quoted:
        return [Seg(f"“{work.title}.”")]
    return _sentence([Seg(work.title, italic=True)])


def _full_segments(work) -> list[Seg]:
    T = type(work).ExternalType
    segs: list[Seg] = []
    authors = _authors(work)
    if authors:
        if work.external_type == T.EDITED_VOLUME:
            authors += ", eds" if (", and " in authors or "," in authors) else ", ed"
        segs.extend(_sentence([Seg(authors)]) + [Seg(" ")])
    segs.extend(_sentence([Seg(_year(work))]) + [Seg(" ")])
    segs.extend(_title_segments(work))
    body = _body_segments(work)
    if body:
        segs.append(Seg(" "))
        segs.extend(body)
    if work.doi:
        segs.append(Seg(" "))
        segs.extend(_sentence([Seg(work.doi_url, href=work.doi_url)]))
    return segs


def _render_html(segs: list[Seg]) -> SafeString:
    out = []
    for s in segs:
        piece = escape(s.text)
        if s.italic:
            piece = f"<i>{piece}</i>"
        if s.href:
            piece = f'<a href="{escape(s.href)}" class="link" target="_blank" rel="noopener">{piece}</a>'
        out.append(piece)
    return mark_safe("".join(out))


def _render_text(segs: list[Seg]) -> str:
    return "".join(s.text for s in segs)


def citation_html(work) -> SafeString:
    return _render_html(_full_segments(work))


def citation_text(work) -> str:
    return _render_text(_full_segments(work))


def source_html(work) -> SafeString:
    """The venue part alone (no authors, year, or title), for headers/cards."""
    segs = _body_segments(work)
    return _render_html(segs) if segs else mark_safe("")
```

- [ ] **Step 4:** Iterate until `uv run pytest works/test_citation.py -q` passes (expect punctuation fiddling — adjust tests only if the *expected Chicago string* was written wrong, never to accommodate sloppy output).
- [ ] **Step 5:** `uv run ruff check works/` green; commit `feat(works): Chicago author-date citation renderer (task #465)`.

### Task 3: Form + form template (kind-gated fieldset, DOI normalization)

**Files:**
- Modify: `works/forms.py` (Meta.fields, widgets, labels; `clean_doi`)
- Modify: `works/templates/works/form.html` (citation fieldset + show/hide JS; relabel "Publication info" → "Citation note")
- Test: `works/test_polish.py`

**Interfaces:**
- Consumes: Task 1 fields.
- Produces: `WorkForm` accepts and saves all structured fields; DOI input normalized to bare form.

- [ ] **Step 1: Failing tests** (append to `works/test_polish.py`):

```python
class TestWorkFormCitation:
    def _data(self, **kw):
        base = {
            "title": "T", "kind": "external",
            "listing_visibility": "public", "content_visibility": "members",
            "external_type": "article", "container_title": "J of X",
            "volume": "1", "issue": "2", "pages": "3–4",
            "doi": "https://doi.org/10.1234/xyz",
        }
        base.update(kw)
        return base

    def test_saves_structured_fields_and_normalizes_doi(self, author):
        from works.forms import WorkForm

        form = WorkForm(self._data(), current_user=author)
        assert form.is_valid(), form.errors
        w = form.save()
        assert w.container_title == "J of X"
        assert w.doi == "10.1234/xyz"

    def test_doi_prefix_variants(self, author):
        from works.forms import WorkForm

        for raw in ("doi:10.1/a", "http://dx.doi.org/10.1/a", "10.1/a"):
            form = WorkForm(self._data(doi=raw), current_user=author)
            assert form.is_valid(), form.errors
            assert form.cleaned_data["doi"] == "10.1/a"
```

(Move the `author` fixture to module level in `works/test_polish.py`, same body as in `test_citation.py`.)

- [ ] **Step 2:** Run → FAIL (fields not on form).
- [ ] **Step 3: Implement** — in `WorkForm.Meta.fields` insert after `"publication_info"`: `"external_type", "container_title", "publisher", "edition", "volume", "issue", "pages", "editors", "translators", "doi", "isbn",`. Widgets: selects/text inputs with the existing classes (`select select-bordered w-full` / `input input-bordered w-full`; short fields `input input-bordered w-full` too). Label `publication_info` → `"Citation note"` with help text `"Free-form citation line. Shown after the formatted citation, or alone if the fields above are empty."`. Add:

```python
    def clean_doi(self):
        doi = (self.cleaned_data.get("doi") or "").strip()
        for prefix in (
            "https://doi.org/", "http://doi.org/",
            "https://dx.doi.org/", "http://dx.doi.org/", "doi:",
        ):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
                break
        return doi
```

- [ ] **Step 4: Template** — in `form.html`, insert a fieldset between the abstract block and the publication-info/date grid:

```html
    <fieldset id="citation-fields" class="space-y-4 border-t border-base-300/60 pt-5">
      <legend class="font-serif text-lg">Publication details</legend>
      <p class="text-xs text-base-content/60 -mt-2">For external publications. Fill what applies, the site renders a Chicago-style citation.</p>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="space-y-1">
          <label for="{{ form.external_type.id_for_label }}" class="block text-sm font-medium">Type</label>
          {{ form.external_type }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.container_title.id_for_label }}" class="block text-sm font-medium">Journal / book title</label>
          {{ form.container_title }}
          <p class="text-xs text-base-content/60">{{ form.container_title.help_text }}</p>
        </div>
        <div class="space-y-1">
          <label for="{{ form.publisher.id_for_label }}" class="block text-sm font-medium">Publisher</label>
          {{ form.publisher }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.edition.id_for_label }}" class="block text-sm font-medium">Edition</label>
          {{ form.edition }}
        </div>
      </div>
      <div class="grid grid-cols-3 gap-4">
        <div class="space-y-1">
          <label for="{{ form.volume.id_for_label }}" class="block text-sm font-medium">Volume</label>
          {{ form.volume }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.issue.id_for_label }}" class="block text-sm font-medium">Issue</label>
          {{ form.issue }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.pages.id_for_label }}" class="block text-sm font-medium">Pages</label>
          {{ form.pages }}
        </div>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="space-y-1">
          <label for="{{ form.editors.id_for_label }}" class="block text-sm font-medium">Editors</label>
          {{ form.editors }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.translators.id_for_label }}" class="block text-sm font-medium">Translators</label>
          {{ form.translators }}
        </div>
        <div class="space-y-1">
          <label for="{{ form.doi.id_for_label }}" class="block text-sm font-medium">DOI</label>
          {{ form.doi }}
          {% if form.doi.errors %}<p class="text-error text-xs mt-1">{{ form.doi.errors|join:", " }}</p>{% endif %}
        </div>
        <div class="space-y-1">
          <label for="{{ form.isbn.id_for_label }}" class="block text-sm font-medium">ISBN</label>
          {{ form.isbn }}
        </div>
      </div>
    </fieldset>
```

Relabel the existing publication_info block to "Citation note" + its help text. Add show/hide JS to the existing bottom `<script>` region (its own IIFE):

```html
  <script>
  (function () {
    var kind = document.getElementById("id_kind");
    var fs = document.getElementById("citation-fields");
    if (!kind || !fs) return;
    function sync() { fs.style.display = kind.value === "external" ? "" : "none"; }
    kind.addEventListener("change", sync);
    sync();
  })();
  </script>
```

- [ ] **Step 5:** Tests + ruff green; commit `feat(works): citation fields on the submission form (task #465)`.

### Task 4: Detail-page presentation + Cite block

**Files:**
- Modify: `works/views.py:detail` (add `citation`, `citation_txt`, `source_line` to context)
- Modify: `works/templates/works/detail.html`
- Test: `works/test_polish.py`

**Interfaces:**
- Consumes: Task 2 `citation_html` / `citation_text` / `source_html`.

- [ ] **Step 1: Failing tests:**

```python
class TestDetailCitation:
    def test_source_line_and_cite_block(self, client, author):
        w = make_work(
            external_type=Work.ExternalType.ARTICLE,
            container_title="Psychoanalytic Review", volume="12", pages="33–58",
            publication_date=datetime.date(2024, 5, 1),
            publication_info="Special issue on the gaze",
        )
        r = client.get(w.get_absolute_url())
        html = r.content.decode()
        assert "<i>Psychoanalytic Review</i>" in html
        assert "Special issue on the gaze" in html   # note AND structured line
        assert "2024" in html                        # date no longer suppressed
        assert "Cite" in html

    def test_external_link_label(self, client):
        w = make_work(title="Linked", slug="linked", url="https://ex.org/p")
        r = client.get(w.get_absolute_url())
        assert "View at publisher" in r.content.decode()
        w2 = make_work(title="Palimp", slug="palimp", kind=Work.Kind.PALIMPSEST,
                       url="https://ex.org/q", listing_visibility="public")
        r2 = client.get(w2.get_absolute_url())
        assert "External link" in r2.content.decode()
```

(`import datetime` at top of `works/test_polish.py`.)

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: View** — in `detail()` add before render:

```python
    from .citation import citation_html, citation_text, source_html

    citation = citation_html(work) if work.kind == Work.Kind.EXTERNAL else ""
    source_line = source_html(work) if work.kind == Work.Kind.EXTERNAL else ""
```

pass `"citation": citation, "citation_txt": citation_text(work) if citation else "", "source_line": source_line` in context.

- [ ] **Step 4: Template** — replace the exclusive publication_info/date block (detail.html lines 49–56) with:

```html
      {% if source_line or work.publication_info or work.publication_date %}
      <div class="text-sm text-base-content/70 space-y-0.5">
        {% if source_line %}<p>{{ source_line }}{% if work.publication_date %} <span class="text-base-content/50">·</span> {{ work.publication_date|date:"Y" }}{% endif %}</p>
        {% elif work.publication_date %}<p>{{ work.publication_date|date:"F j, Y" }}</p>{% endif %}
        {% if work.publication_info %}<p>{{ work.publication_info }}</p>{% endif %}
        {% if work.doi or work.isbn %}
        <p class="text-xs text-base-content/50">
          {% if work.doi %}DOI: <a href="{{ work.doi_url }}" target="_blank" rel="noopener" class="hover:text-primary border-b border-dotted border-base-content/40">{{ work.doi }}</a>{% endif %}
          {% if work.doi and work.isbn %} · {% endif %}
          {% if work.isbn %}ISBN {{ work.isbn }}{% endif %}
        </p>
        {% endif %}
      </div>
      {% endif %}
```

Wait — when `source_line` is empty but publication_info exists, the old rendering must be preserved: publication_info shows; date shows too now (fix). The block above handles all cases; when both `source_line` empty and info present, info shows and the date branch adds "F j, Y" — adjust so date also shows alongside info: change the `elif` to always show the long date when there is no source_line: `{% if not source_line and work.publication_date %}<p>{{ work.publication_date|date:"F j, Y" }}</p>{% endif %}` placed before the info line. Use that form in the implementation.

External-link buttons (3 occurrences in detail.html): label with `{% if work.kind == "external" %}View at publisher{% else %}External link{% endif %} →`.

Cite block, inserted after the abstract section (before `body_html`):

```html
  {% if citation %}
  <section class="border-t border-base-300/50 pt-6 space-y-2">
    <h2 class="text-xs uppercase tracking-wider text-base-content/60">Cite</h2>
    <p class="text-sm text-base-content/80 pl-8 -indent-8">{{ citation }}</p>
    <button type="button" class="btn btn-ghost btn-xs" id="copy-citation"
            data-citation="{{ citation_txt }}">Copy citation</button>
  </section>
  <script>
  (function () {
    var btn = document.getElementById("copy-citation");
    if (!btn || !navigator.clipboard) return;
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(btn.dataset.citation).then(function () {
        btn.textContent = "Copied ✓";
        setTimeout(function () { btn.textContent = "Copy citation"; }, 2000);
      });
    });
  })();
  </script>
  {% endif %}
```

- [ ] **Step 5:** Tests + ruff green; commit `feat(works): citation display on the work page, Cite block, date fix (task #465)`.

### Task 5: Index ordering (`?sort=`)

**Files:**
- Modify: `works/views.py:index`
- Modify: `works/templates/works/index.html` (Sort select in the filter form)
- Test: `works/test_polish.py`

**Interfaces:**
- Produces: `?sort=random|year|added|author` on `works:index`; context keys `selected_sort`, `sort_choices`.

- [ ] **Step 1: Failing tests:**

```python
class TestIndexSort:
    @pytest.fixture(autouse=True)
    def works(self, author, django_user_model):
        z = django_user_model.objects.create_user(
            email="z@example.org", password="x", first_name="Ann", last_name="Zed",
        )
        self.a = make_work(title="Alpha", slug="alpha",
                           publication_date=datetime.date(2020, 1, 1))
        WorkAuthor.objects.create(work=self.a, user=z, display_order=0)
        self.b = make_work(title="Beta", slug="beta",
                           publication_date=datetime.date(2024, 1, 1), author=author)
        self.c = make_work(title="Gamma", slug="gamma")  # undated, no authors

    def _titles(self, client, sort):
        r = client.get("/works/", {"sort": sort})
        return [w.title for w in r.context["works"]]

    def test_year_newest_first_undated_last(self, client):
        assert self._titles(client, "year") == ["Beta", "Alpha", "Gamma"]

    def test_added_recent_first(self, client):
        assert self._titles(client, "added") == ["Gamma", "Beta", "Alpha"]

    def test_author_alpha_blank_last(self, client):
        assert self._titles(client, "author") == ["Beta", "Alpha", "Gamma"]  # Swales < Zed

    def test_default_and_bogus_return_all(self, client):
        for sort in ("", "random", "nonsense"):
            r = client.get("/works/", {"sort": sort} if sort else {})
            assert {w.title for w in r.context["works"]} == {"Alpha", "Beta", "Gamma"}
            assert r.context["selected_sort"] == ("random" if sort != "nonsense" else "random")
```

(`make_work` gains an optional `author` kwarg already defined in `test_citation.py`'s local helper — define once in `test_polish.py` with the author kwarg and reuse.)

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** in `index()` after the filters:

```python
    from django.db.models import F, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce, Lower, NullIf

    SORTS = ("random", "year", "added", "author")
    sort = request.GET.get("sort") or "random"
    if sort not in SORTS:
        sort = "random"
    if sort == "year":
        qs = qs.order_by(F("publication_date").desc(nulls_last=True), "-created_at")
    elif sort == "added":
        qs = qs.order_by("-created_at")
    elif sort == "author":
        first_author = Subquery(
            WorkAuthor.objects.filter(work=OuterRef("pk"))
            .order_by("display_order")
            .values("user__last_name")[:1]
        )
        qs = qs.annotate(
            _author_key=Coalesce(
                NullIf(Lower(first_author), Value("")),
                NullIf(Lower("external_authors"), Value("")),
            )
        ).order_by(F("_author_key").asc(nulls_last=True), "title")
    else:
        qs = qs.order_by("?")
```

Context additions: `"selected_sort": sort, "sort_choices": [("random", "Random"), ("year", "Publication year"), ("added", "Recently added"), ("author", "Author A–Z")]`.

- [ ] **Step 4: Template** — add to the filter form after the Year select:

```html
    <div>
      <label for="filter-sort" class="block text-xs uppercase tracking-wider text-base-content/60 mb-1">Sort</label>
      <select id="filter-sort" name="sort" class="select select-bordered select-sm">
        {% for value, label in sort_choices %}
        <option value="{{ value }}" {% if value == selected_sort %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </div>
```

Include `sort` in the Clear-link condition (`{% if selected_kind or ... or selected_sort != "random" %}`).

- [ ] **Step 5:** Tests + ruff green; commit `feat(works): sort options with random default on /works/ (task #465)`.

### Task 6: Grid/list toggle + list row

**Files:**
- Modify: `works/views.py:index` (view param + cookie)
- Modify: `works/templates/works/index.html` (toggle + list branch)
- Create: `works/templates/works/_row.html`
- Test: `works/test_polish.py`

**Interfaces:**
- Produces: `?view=grid|list`, cookie `works_view` (1 year) set only on explicit `?view=`; context key `view_mode`; `_row.html` expects `work`.

- [ ] **Step 1: Failing tests:**

```python
class TestViewToggle:
    def test_default_grid(self, client):
        make_work()
        r = client.get("/works/")
        assert r.context["view_mode"] == "grid"

    def test_explicit_list_sets_cookie(self, client):
        make_work()
        r = client.get("/works/", {"view": "list"})
        assert r.context["view_mode"] == "list"
        assert r.cookies["works_view"].value == "list"

    def test_cookie_remembered(self, client):
        make_work()
        client.cookies["works_view"] = "list"
        r = client.get("/works/")
        assert r.context["view_mode"] == "list"
        assert "works_view" not in r.cookies  # not re-set on read

    def test_query_beats_cookie_and_bogus_falls_back(self, client):
        make_work()
        client.cookies["works_view"] = "list"
        assert client.get("/works/", {"view": "grid"}).context["view_mode"] == "grid"
        assert client.get("/works/", {"view": "x"}).context["view_mode"] == "list"
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: View** — at the end of `index()`:

```python
    view_param = request.GET.get("view") or ""
    view_mode = view_param if view_param in ("grid", "list") else (
        request.COOKIES.get("works_view") if request.COOKIES.get("works_view") in ("grid", "list") else "grid"
    )
    response = render(request, "works/index.html", {..., "view_mode": view_mode})
    if view_param in ("grid", "list"):
        response.set_cookie("works_view", view_param, max_age=365 * 24 * 3600, samesite="Lax")
    return response
```

- [ ] **Step 4: Templates** — toggle next to the filter form's Filter button (inside the form area but as links, using `{% querystring %}`):

```html
    <div class="join ml-auto" role="group" aria-label="Layout">
      <a href="{% querystring view='grid' %}" title="Grid"
         class="btn btn-sm join-item {% if view_mode == 'grid' %}btn-active{% endif %}">▦</a>
      <a href="{% querystring view='list' %}" title="List"
         class="btn btn-sm join-item {% if view_mode == 'list' %}btn-active{% endif %}">≡</a>
    </div>
```

Add `<input type="hidden" name="view" value="{{ view_mode }}">` inside the filter form so submitting filters keeps the layout. Results branch:

```html
  {% if works %}
    {% if view_mode == "list" %}
    <ul class="divide-y divide-base-300/40">
      {% for work in works %}{% include "works/_row.html" %}{% endfor %}
    </ul>
    {% else %}
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-5 gap-y-8">
      {% for work in works %}{% include "works/_card.html" %}{% endfor %}
    </div>
    {% endif %}
  {% else %} ... {% endif %}
```

`_row.html`:

```html
{# A single Work as a compact citation-style list row. Expects `work`. #}
<li class="py-3 flex flex-wrap items-baseline gap-x-2">
  <p class="text-sm text-base-content/80 grow basis-full sm:basis-auto pl-8 -indent-8">
    {% for wa in work.authorships.all %}{% if not forloop.first %}; {% endif %}<a href="{% url 'directory_detail' wa.user.profile.directory_slug %}" class="hover:text-primary">{{ wa.user.first_name }} {{ wa.user.last_name }}</a>{% endfor %}{% if work.external_authors %}{% if work.authorships.all %}; {% endif %}{{ work.external_authors }}{% endif %}{% if work.authorships.all or work.external_authors %}.{% endif %}
    {% if work.publication_date %}{{ work.publication_date|date:"Y" }}.{% endif %}
    <a href="{{ work.get_absolute_url }}" class="font-medium text-base-content hover:text-primary">{{ work.title }}</a>.
    {% if work.kind == "external" %}{% with sl=work|work_source_line %}{% if sl %}{{ sl }}{% elif work.publication_info %}{{ work.publication_info }}{% endif %}{% endwith %}{% elif work.publication_info %}{{ work.publication_info }}{% endif %}
  </p>
  <span class="text-[11px] uppercase tracking-wider text-base-content/50">{{ work.get_kind_display }}</span>
  {% if work.listing_visibility == "members" %}<span class="badge badge-ghost badge-xs">Members</span>{% endif %}
  {% if work.files.all %}<span class="text-[11px] text-base-content/50" title="PDF available">PDF</span>{% endif %}
  {% if work.video %}<span class="text-[11px] text-base-content/50" title="Video available">Video</span>{% endif %}
</li>
```

This needs a `work_source_line` template filter: create `works/templatetags/works_citation.py`:

```python
from django import template

from works.citation import source_html

register = template.Library()


@register.filter
def work_source_line(work):
    return source_html(work)
```

(`works/templatetags/` already exists; load with `{% load works_citation %}` at the top of `_row.html`.)

- [ ] **Step 5:** Tests + ruff green; commit `feat(works): grid/list toggle with citation-style rows (task #465)`.

### Task 7: Card venue line

**Files:**
- Modify: `works/templates/works/_card.html`

- [ ] **Step 1:** After the authors `<p>`, add:

```html
    {% if work.kind == "external" and work.container_title or work.kind == "external" and work.publisher %}
    <p class="text-[11px] text-base-content/55 line-clamp-1"><i>{{ work.container_title|default:work.publisher }}</i></p>
    {% endif %}
```

(Year already renders in the meta line below; no duplicate.)

- [ ] **Step 2:** Eyeball via `uv run pytest works/ -q` (no template errors) and commit `style(works): venue line on catalog cards (task #465)`.

### Task 8: `backfill_citations` management command

**Files:**
- Create: `works/management/commands/backfill_citations.py`
- Test: `works/test_polish.py`

**Interfaces:**
- Consumes: JSON file: `[{"slug": "...", "fields": {"external_type": "article", "container_title": "...", ...}}, ...]` — keys limited to `Work.STRUCTURED_CITATION_FIELDS`.
- Produces: fills only currently-empty fields; `--dry-run` prints without writing; reports per-work applied/skipped counts.

- [ ] **Step 1: Failing tests:**

```python
import json


class TestBackfillCitations:
    def test_fills_only_empty_and_dry_run(self, tmp_path, capsys):
        from django.core.management import call_command

        w = make_work(title="Fill Me", slug="fill-me", container_title="Kept")
        mapping = [{"slug": "fill-me", "fields": {
            "container_title": "Overwritten?", "publisher": "Routledge",
        }}]
        p = tmp_path / "m.json"
        p.write_text(json.dumps(mapping))

        call_command("backfill_citations", str(p), "--dry-run")
        w.refresh_from_db()
        assert w.publisher == ""            # dry run wrote nothing

        call_command("backfill_citations", str(p))
        w.refresh_from_db()
        assert w.publisher == "Routledge"   # empty field filled
        assert w.container_title == "Kept"  # member data never overwritten

    def test_unknown_slug_and_field_rejected(self, tmp_path):
        from django.core.management import CommandError, call_command

        p = tmp_path / "m.json"
        p.write_text(json.dumps([{"slug": "nope", "fields": {"publisher": "X"}}]))
        with pytest.raises(CommandError):
            call_command("backfill_citations", str(p))
        p.write_text(json.dumps([{"slug": "fill-me", "fields": {"title": "hack"}}]))
        make_work(title="Fill Me", slug="fill-me")
        with pytest.raises(CommandError):
            call_command("backfill_citations", str(p))
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement:**

```python
"""Apply a curated citation mapping to existing Works (task #465).

The mapping JSON is hand-reviewed (import-staging/), one entry per work:
    [{"slug": "...", "fields": {"container_title": "...", ...}}, ...]
Only fields in Work.STRUCTURED_CITATION_FIELDS are allowed, and only
currently-empty fields are filled — member edits are never overwritten.
Idempotent; run with --dry-run first.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from works.models import Work


class Command(BaseCommand):
    help = "Backfill structured citation fields from a reviewed JSON mapping."

    def add_arguments(self, parser):
        parser.add_argument("mapping")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        with open(opts["mapping"]) as fh:
            entries = json.load(fh)
        allowed = set(Work.STRUCTURED_CITATION_FIELDS)
        applied = skipped = 0
        for entry in entries:
            slug, fields = entry.get("slug"), entry.get("fields") or {}
            bad = set(fields) - allowed
            if bad:
                raise CommandError(f"{slug}: fields not allowed: {sorted(bad)}")
            try:
                work = Work.objects.get(slug=slug)
            except Work.DoesNotExist:
                raise CommandError(f"No work with slug {slug!r}")
            changed = []
            for name, value in fields.items():
                if getattr(work, name):
                    skipped += 1
                    continue
                setattr(work, name, value)
                changed.append(name)
            if changed:
                applied += len(changed)
                verb = "would set" if opts["dry_run"] else "set"
                self.stdout.write(f"{slug}: {verb} {', '.join(changed)}")
                if not opts["dry_run"]:
                    work.save(update_fields=changed + ["updated_at"])
        self.stdout.write(self.style.SUCCESS(
            f"{applied} field(s) {'would be ' if opts['dry_run'] else ''}applied, "
            f"{skipped} skipped (already set)."
        ))
```

- [ ] **Step 4:** Tests + ruff green; commit `feat(works): backfill_citations command for curated migration (task #465)`.

### Task 9: Full-suite verification

- [ ] `uv run pytest -q` (whole suite) green.
- [ ] `uv run ruff check .` green.
- [ ] `npm run build:css` (new classes: `-indent-8`, `pl-8`, `join-item`, `line-clamp-1` — all appear in templates so Tailwind picks them up).
- [ ] Smoke-check `/works/` and a work detail page in the dev server (grid/list toggle, sort select, citation form gating).

### Task 10 (deploy-time, after merge): prod backfill

- [ ] Pull external Works' citation fields from prod (read-only; Rico may need to run the SSH command).
- [ ] Hand-write `import-staging/works-citations-2026-07.json`; Rico eyeballs it.
- [ ] On prod: `manage.py backfill_citations … --dry-run`, review, then apply.

## Self-Review Notes

- Spec coverage: §1 → Tasks 1–3; renderer → Task 2; §2 → Tasks 4, 7; §3 → Task 5; §4 → Task 6; §5 → Tasks 8, 10. ✓
- `Meta.ordering` untouched (Task 5 orders explicitly in the view). ✓
- Names consistent: `citation_html`/`citation_text`/`source_html`, `STRUCTURED_CITATION_FIELDS`, cookie `works_view`, param names `sort`/`view`. ✓
