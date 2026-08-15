# Document Replacement + Revision History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Web Coordinator replace a document's PDF and metadata from a site-side admin surface, keeping a restorable history of every prior state.

**Architecture:** A role-based surface under the Web Coordinator admin (`/admin-tools/web-coordinator/documents/`), backed by a `DocumentRevision` snapshot model written through one chokepoint on `Document`. The public detail page gains only a gated deep link.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5, private S3 storage via `core.storage.private_storage`.

**Spec:** `docs/superpowers/specs/2026-08-15-document-replacement-and-revisions-design.md`

## Global Constraints

- Gate is `superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR)`. Never `is_staff`, never `WEB_DEVELOPER`.
- `snapshot_revision` must re-read from the DB, never trust `self` (ModelForm mutates instances in place — #532).
- Never copy a file in storage; assign the name (`rev.file = doc.file.name`).
- Restore is forward-only: snapshot current state before writing an old one back.
- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, …), never hardcoded colors.
- Any CSS class set in Python must already appear in a committed template (`tailwind-classes-set-in-python`).
- Run `uv run pytest documents -q` and `uv run ruff check .` before each commit.

---

### Task 1: The gate

**Files:**
- Create: `documents/permissions.py`
- Test: `documents/test_admin_surface.py`

**Interfaces:**
- Produces: `can_manage_documents(user) -> bool`, `manage_documents_required(view)`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Web Coordinator's document management surface (task #592)."""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Profile, User
from core.models import StaffRole
from documents.models import Document


def _doc(**kwargs) -> Document:
    defaults = dict(
        title="Test doc", slug="test-doc",
        category=Document.Category.FORMATION,
        summary="A test document",
        file=SimpleUploadedFile("old.pdf", b"%PDF-1.4\nold\n",
                                content_type="application/pdf"),
    )
    defaults.update(kwargs)
    return Document.objects.create(**defaults)


def _user(email="u@x.test", role=Profile.Role.ANALYST) -> User:
    u = User.objects.create_user(email=email)
    u.profile.role = role
    u.profile.save(update_fields=["role"])
    return u


def _coordinator(email="wc@x.test") -> User:
    u = _user(email)
    StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"},
    )[0].holders.add(u)
    return u


@pytest.mark.django_db
def test_can_manage_rejects_anonymous():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(None) is False


@pytest.mark.django_db
def test_can_manage_rejects_plain_member():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(_user()) is False


@pytest.mark.django_db
def test_can_manage_allows_web_coordinator():
    from documents.permissions import can_manage_documents
    assert can_manage_documents(_coordinator()) is True


@pytest.mark.django_db
def test_can_manage_allows_superuser():
    from documents.permissions import can_manage_documents
    u = User.objects.create_superuser(email="su@x.test", password="x")
    assert can_manage_documents(u) is True


@pytest.mark.django_db
def test_can_manage_rejects_web_developer():
    """The Web Developer holds the Django admin path, not this surface."""
    from documents.permissions import can_manage_documents
    u = _user("wd@x.test")
    StaffRole.objects.get_or_create(
        key=StaffRole.WEB_DEVELOPER, defaults={"name": "Web Developer"},
    )[0].holders.add(u)
    assert can_manage_documents(u) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest documents/test_admin_surface.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'documents.permissions'`

- [ ] **Step 3: Implement**

```python
"""Who may manage institutional documents.

The management surface lives under the Web Coordinator admin, so it is gated
to that role alone: pairing in the Web Developer would grant a child page to
a role that 403s on its parent hub, and the Web Developer already reaches
these fields through the Django admin.
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from core.access import has_staff_role
from core.models import StaffRole


def can_manage_documents(user) -> bool:
    """True for the Web Coordinator (and superusers, who hold every role)."""
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR)


def manage_documents_required(view):
    """Anonymous → login (returning here); signed-in non-holder → 403.

    Shaped like ``core.access._guard`` but expressed over this app's own
    predicate, so the template flag and the view gate cannot drift.
    """

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not can_manage_documents(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return _wrapped
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest documents/test_admin_surface.py -q` → PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add documents/permissions.py documents/test_admin_surface.py
git commit -m "feat(documents): gate document management to the Web Coordinator (task #592)"
```

---

### Task 2: The revision model and the snapshot chokepoint

**Files:**
- Modify: `documents/models.py`
- Create: `documents/migrations/0013_documentrevision.py` (via makemigrations)
- Test: `documents/test_revisions.py`

**Interfaces:**
- Produces: `SNAPSHOT_FIELDS`, `DocumentRevision`, `Document.snapshot_revision(user=None, note="") -> DocumentRevision`, `DocumentRevision.changes_against(other) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
"""Revision snapshots for documents (task #592)."""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from documents.models import Document, DocumentRevision

from .test_admin_surface import _doc


@pytest.mark.django_db
def test_snapshot_captures_current_state():
    d = _doc(title="Before")
    rev = d.snapshot_revision(note="why")
    assert rev.title == "Before"
    assert rev.document_id == d.pk
    assert rev.note == "why"
    assert rev.file.name == d.file.name


@pytest.mark.django_db
def test_snapshot_records_who():
    d = _doc()
    u = User.objects.create_user(email="who@x.test")
    assert d.snapshot_revision(user=u).saved_by_id == u.pk


@pytest.mark.django_db
def test_snapshot_ignores_in_place_mutation():
    """A ModelForm mutates its instance during validation (#532), so the
    snapshot must read the database, not the object handed to it."""
    d = _doc(title="Stored")
    d.title = "Mutated in memory"
    rev = d.snapshot_revision()
    assert rev.title == "Stored"


@pytest.mark.django_db
def test_changes_against_reports_differing_fields():
    d = _doc(title="Old title", summary="Old summary")
    rev = d.snapshot_revision()
    d.title = "New title"
    d.save(update_fields=["title"])
    changes = rev.changes_against(d)
    assert [c["field"] for c in changes] == ["title"]
    assert changes[0]["old"] == "Old title"
    assert changes[0]["new"] == "New title"
    assert changes[0]["label"]


@pytest.mark.django_db
def test_changes_against_reports_a_replaced_file():
    d = _doc()
    rev = d.snapshot_revision()
    d.file = SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                content_type="application/pdf")
    d.save()
    assert [c["field"] for c in rev.changes_against(d)] == ["file"]


@pytest.mark.django_db
def test_revisions_are_newest_first():
    d = _doc()
    first = d.snapshot_revision(note="first")
    second = d.snapshot_revision(note="second")
    assert list(d.revisions.all()) == [second, first]


@pytest.mark.django_db
def test_revision_file_points_at_the_same_object():
    """Snapshots reference the stored key; they never copy the file."""
    d = _doc()
    rev = d.snapshot_revision()
    assert rev.file.name == d.file.name
    assert DocumentRevision.objects.count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest documents/test_revisions.py -q`
Expected: FAIL — `ImportError: cannot import name 'DocumentRevision'`

- [ ] **Step 3: Implement — append to `documents/models.py`**

```python
#: The fields a revision snapshots — exactly the set the management form
#: edits, so a restore can write every one of them back.
SNAPSHOT_FIELDS = (
    "title", "summary", "description", "notice", "body", "effective_date",
    "listing_visibility", "content_visibility", "display_order",
)


class DocumentRevision(models.Model):
    """A document's state *before* one save (task #592).

    Each row reads "the document used to be this"; the current state always
    lives on the ``Document``. That ordering means the first edit of an
    already-seeded document captures its original for free, with no synthetic
    baseline row.

    ``file`` holds the storage key the document carried at the time. Django
    has not deleted a replaced ``FileField`` target since 1.3, so the old
    object is still in the bucket and two rows can point at one immutable
    file. Nothing here copies or deletes it.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="revisions",
    )
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    notice = models.CharField(max_length=500, blank=True)
    body = models.TextField(blank=True)
    file = models.FileField(
        upload_to="documents/%Y/", storage=private_storage, blank=True,
    )
    effective_date = models.DateField(null=True, blank=True)
    listing_visibility = models.CharField(max_length=16, blank=True)
    content_visibility = models.CharField(max_length=16, blank=True)
    display_order = models.IntegerField(default=0)
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="document_revisions",
    )
    saved_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-saved_at", "-pk")

    def __str__(self) -> str:
        return f"{self.title} @ {self.saved_at:%Y-%m-%d %H:%M}"

    def changes_against(self, other) -> list[dict]:
        """What changed between this snapshot and ``other`` — the state that
        came after it (the next revision, or the live Document for the
        newest one)."""
        out = []
        for name in SNAPSHOT_FIELDS:
            old, new = getattr(self, name), getattr(other, name)
            if old != new:
                out.append({
                    "field": name,
                    "label": Document._meta.get_field(name).verbose_name,
                    "old": old,
                    "new": new,
                })
        old_file = self.file.name or ""
        new_file = other.file.name or ""
        if old_file != new_file:
            out.append({
                "field": "file", "label": "file",
                "old": old_file, "new": new_file,
            })
        return out
```

And on `Document`, below `get_absolute_url`:

```python
    def snapshot_revision(self, user=None, note: str = "") -> "DocumentRevision":
        """Record the state this document is in *now*, before it changes.

        Reads the row back from the database rather than trusting ``self``:
        a ``ModelForm`` mutates its instance in place during validation, which
        is what made ``changed_reviewable_fields()`` silently wrong in #532.
        Re-reading means no caller has to remember to snapshot before binding.
        """
        current = Document.objects.get(pk=self.pk)
        rev = DocumentRevision(document=current, saved_by=user, note=note)
        for name in SNAPSHOT_FIELDS:
            setattr(rev, name, getattr(current, name))
        rev.file = current.file.name or ""
        rev.save()
        return rev
```

- [ ] **Step 4: Generate the migration and run the tests**

```bash
uv run python manage.py makemigrations documents
uv run pytest documents/test_revisions.py -q
```
Expected: migration `0013_documentrevision.py` created; tests PASS (7).

- [ ] **Step 5: Commit**

```bash
git add documents/models.py documents/migrations/0013_documentrevision.py documents/test_revisions.py
git commit -m "feat(documents): snapshot a document's prior state on every save (task #592)"
```

---

### Task 3: Restore

**Files:**
- Create: `documents/services.py`
- Test: `documents/test_revisions.py` (append)

**Interfaces:**
- Consumes: `SNAPSHOT_FIELDS`, `Document.snapshot_revision`
- Produces: `restore_revision(document, revision, user=None) -> Document`

- [ ] **Step 1: Write the failing tests (append to `documents/test_revisions.py`)**

```python
@pytest.mark.django_db
def test_restore_puts_prior_values_back():
    from documents.services import restore_revision
    d = _doc(title="Original", summary="Original summary")
    rev = d.snapshot_revision()
    d.title = "Replaced"
    d.summary = "Replaced summary"
    d.save()
    restore_revision(d, rev)
    d.refresh_from_db()
    assert d.title == "Original"
    assert d.summary == "Original summary"


@pytest.mark.django_db
def test_restore_puts_the_prior_file_back():
    from documents.services import restore_revision
    d = _doc()
    original_name = d.file.name
    rev = d.snapshot_revision()
    d.file = SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                content_type="application/pdf")
    d.save()
    assert d.file.name != original_name
    restore_revision(d, rev)
    d.refresh_from_db()
    assert d.file.name == original_name


@pytest.mark.django_db
def test_restore_is_forward_only():
    """Restoring is itself an edit: the pre-restore state becomes a revision."""
    from documents.services import restore_revision
    d = _doc(title="Original")
    rev = d.snapshot_revision()
    d.title = "Replaced"
    d.save()
    restore_revision(d, rev)
    assert d.revisions.count() == 2
    assert d.revisions.first().title == "Replaced"


@pytest.mark.django_db
def test_restore_refuses_a_revision_from_another_document():
    from documents.services import restore_revision
    a = _doc(slug="doc-a")
    b = _doc(slug="doc-b", title="B")
    rev = b.snapshot_revision()
    with pytest.raises(ValueError):
        restore_revision(a, rev)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest documents/test_revisions.py -q` → FAIL, `No module named 'documents.services'`

- [ ] **Step 3: Implement `documents/services.py`**

```python
"""Document management side-effects shared by the admin surface (task #592)."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import SNAPSHOT_FIELDS, Document, DocumentRevision


@transaction.atomic
def restore_revision(
    document: Document, revision: DocumentRevision, user=None,
) -> Document:
    """Put ``revision``'s state back onto ``document``.

    Forward-only: the current state is snapshotted first, so restoring is
    itself an edit in the history and nothing is ever destroyed.
    """
    if revision.document_id != document.pk:
        raise ValueError("That revision belongs to a different document.")

    when = timezone.localtime(revision.saved_at).strftime("%b %-d, %Y at %H:%M")
    document.snapshot_revision(
        user=user, note=f"Before restoring the version saved {when}",
    )
    for name in SNAPSHOT_FIELDS:
        setattr(document, name, getattr(revision, name))
    document.file = revision.file.name or ""
    document.save()
    return document
```

- [ ] **Step 4: Run tests** → `uv run pytest documents/test_revisions.py -q` PASS (11)

- [ ] **Step 5: Commit**

```bash
git add documents/services.py documents/test_revisions.py
git commit -m "feat(documents): restore a revision, forward-only (task #592)"
```

---

### Task 4: The edit form

**Files:**
- Create: `documents/forms.py`
- Test: `documents/test_admin_surface.py` (append)

**Interfaces:**
- Produces: `DocumentEditForm` (ModelForm over Document + a non-model `note` CharField)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_form_display_order_is_optional():
    """A choices/default model field lands on a ModelForm as REQUIRED unless
    told otherwise — the trap from new-modelform-field-is-required-by-default."""
    from documents.forms import DocumentEditForm
    d = _doc()
    form = DocumentEditForm(
        {"title": "T", "listing_visibility": "public",
         "content_visibility": "public", "body": "text"},
        instance=d,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["display_order"] == 0


@pytest.mark.django_db
def test_form_rejects_public_contents_under_members_listing():
    from documents.forms import DocumentEditForm
    d = _doc()
    form = DocumentEditForm(
        {"title": "T", "listing_visibility": "members",
         "content_visibility": "public", "display_order": 0},
        instance=d,
    )
    assert not form.is_valid()
    assert "content_visibility" in form.errors


@pytest.mark.django_db
def test_form_keeps_the_existing_file_when_none_uploaded():
    from documents.forms import DocumentEditForm
    d = _doc()
    original = d.file.name
    form = DocumentEditForm(
        {"title": "Renamed", "listing_visibility": "public",
         "content_visibility": "public", "display_order": 0},
        instance=d,
    )
    assert form.is_valid(), form.errors
    assert form.save().file.name == original
```

- [ ] **Step 2: Run** → FAIL, `No module named 'documents.forms'`

- [ ] **Step 3: Implement `documents/forms.py`**

```python
"""Forms for the Web Coordinator's document management surface (task #592)."""

from __future__ import annotations

from django import forms

from .models import Document

_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"
_SELECT = "select select-bordered w-full"


class DocumentEditForm(forms.ModelForm):
    """Content and presentation only.

    Identity fields — slug (the URL, with no redirect if changed), category,
    owning workgroup, authors, superseded_by — stay in the Django admin.
    """

    note = forms.CharField(
        required=False, max_length=255,
        label="What changed?",
        help_text="Optional. Recorded against the previous version.",
        widget=forms.TextInput(attrs={"class": _INPUT}),
    )

    class Meta:
        model = Document
        fields = (
            "title", "summary", "description", "notice", "file", "body",
            "effective_date", "listing_visibility", "content_visibility",
            "display_order",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT}),
            "summary": forms.TextInput(attrs={"class": _INPUT}),
            "notice": forms.TextInput(attrs={"class": _INPUT}),
            "description": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4}),
            "body": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 12}),
            "effective_date": forms.DateInput(
                attrs={"class": _INPUT, "type": "date"}, format="%Y-%m-%d",
            ),
            "listing_visibility": forms.Select(attrs={"class": _SELECT}),
            "content_visibility": forms.Select(attrs={"class": _SELECT}),
            "display_order": forms.NumberInput(attrs={"class": _INPUT}),
            "file": forms.ClearableFileInput(
                attrs={"class": "file-input file-input-bordered w-full",
                       "accept": "application/pdf"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A model field with a default but no blank=True arrives required.
        self.fields["display_order"].required = False
        self.fields["file"].required = False

    def clean_display_order(self):
        value = self.cleaned_data.get("display_order")
        return 0 if value in (None, "") else value
```

- [ ] **Step 4: Run** → `uv run pytest documents/test_admin_surface.py -q` PASS (8)

- [ ] **Step 5: Commit**

```bash
git add documents/forms.py documents/test_admin_surface.py
git commit -m "feat(documents): the document edit form (task #592)"
```

---

### Task 5: The management views, URLs and templates

**Files:**
- Create: `documents/views_admin.py`, `documents/urls_admin.py`
- Create: `documents/templates/documents/admin/index.html`, `documents/templates/documents/admin/edit.html`
- Modify: `config/urls.py`
- Test: `documents/test_admin_surface.py` (append)

**Interfaces:**
- Consumes: `manage_documents_required`, `DocumentEditForm`, `Document.snapshot_revision`, `restore_revision`
- Produces: url names `documents_admin:index`, `documents_admin:edit`, `documents_admin:revision_download`, `documents_admin:restore`; `revision_rows(document)`

- [ ] **Step 1: Write the failing tests**

```python
from django.urls import reverse


@pytest.mark.django_db
def test_index_redirects_anonymous_to_login(client):
    _doc()
    resp = client.get(reverse("documents_admin:index"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_index_forbidden_for_plain_member(client):
    _doc()
    client.force_login(_user())
    assert client.get(reverse("documents_admin:index")).status_code == 403


@pytest.mark.django_db
def test_index_lists_documents_for_the_coordinator(client):
    _doc(title="Scholar Formation Guidelines")
    client.force_login(_coordinator())
    resp = client.get(reverse("documents_admin:index"))
    assert resp.status_code == 200
    assert b"Scholar Formation Guidelines" in resp.content


@pytest.mark.django_db
def test_edit_replaces_the_file_and_writes_a_revision(client):
    d = _doc()
    original = d.file.name
    client.force_login(_coordinator())
    resp = client.post(
        reverse("documents_admin:edit", args=[d.slug]),
        {
            "title": d.title, "summary": d.summary, "description": "",
            "notice": "", "body": "", "effective_date": "2026-08-15",
            "listing_visibility": "public", "content_visibility": "public",
            "display_order": 10, "note": "New board copy",
            "file": SimpleUploadedFile("new.pdf", b"%PDF-1.4\nnew\n",
                                       content_type="application/pdf"),
        },
    )
    assert resp.status_code == 302
    d.refresh_from_db()
    assert d.file.name != original
    assert str(d.effective_date) == "2026-08-15"
    rev = d.revisions.get()
    assert rev.file.name == original
    assert rev.note == "New board copy"


@pytest.mark.django_db
def test_edit_writes_a_revision_for_a_metadata_only_change(client):
    d = _doc(title="Old")
    client.force_login(_coordinator())
    client.post(
        reverse("documents_admin:edit", args=[d.slug]),
        {"title": "New", "summary": "", "description": "", "notice": "",
         "body": "", "effective_date": "", "listing_visibility": "public",
         "content_visibility": "public", "display_order": 0, "note": ""},
    )
    d.refresh_from_db()
    assert d.title == "New"
    assert d.revisions.get().title == "Old"
```

- [ ] **Step 2: Run** → FAIL, `NoReverseMatch: 'documents_admin' is not a registered namespace`

- [ ] **Step 3: Implement**

`documents/views_admin.py`:

```python
"""The Web Coordinator's document management surface (task #592).

Role-based, like every other admin area here: it lives under the Web
Coordinator admin rather than on the object's own public page, which also
keeps the revision history off the public template entirely.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DocumentEditForm
from .models import Document, DocumentRevision
from .permissions import manage_documents_required
from .services import restore_revision


def revision_rows(document: Document) -> list[dict]:
    """Each revision paired with what changed between it and the state that
    followed — the next revision, or the live document for the newest."""
    rows = []
    successor = document
    for rev in document.revisions.select_related("saved_by"):
        rows.append({"revision": rev, "changes": rev.changes_against(successor)})
        successor = rev
    return rows


@manage_documents_required
def index(request):
    documents = (
        Document.objects.select_related("owning_workgroup")
        .order_by("category", "display_order", "title")
    )
    return render(request, "documents/admin/index.html", {
        "documents": documents,
    })


@manage_documents_required
def edit(request, slug: str):
    doc = get_object_or_404(Document, slug=slug)

    if request.method != "POST":
        form = DocumentEditForm(instance=doc)
    else:
        form = DocumentEditForm(request.POST, request.FILES, instance=doc)
        if form.is_valid():
            # Safe before or after binding — snapshot_revision re-reads the row.
            doc.snapshot_revision(
                user=request.user, note=form.cleaned_data.get("note", ""),
            )
            form.save()
            messages.success(
                request,
                "Document updated. The previous version is in its history.",
            )
            return redirect("documents_admin:edit", slug=doc.slug)

    return render(request, "documents/admin/edit.html", {
        "doc": doc, "form": form, "rows": revision_rows(doc),
    })


@manage_documents_required
def revision_download(request, slug: str, pk: int):
    revision = get_object_or_404(DocumentRevision, pk=pk, document__slug=slug)
    if not revision.file:
        raise Http404()
    name = revision.file.name.rsplit("/", 1)[-1]
    return FileResponse(revision.file.open("rb"), as_attachment=False,
                        filename=name)


@require_POST
@manage_documents_required
def restore(request, slug: str, pk: int):
    doc = get_object_or_404(Document, slug=slug)
    revision = get_object_or_404(DocumentRevision, pk=pk, document=doc)
    restore_revision(doc, revision, user=request.user)
    messages.success(
        request,
        "Restored. The version you replaced is still in the history.",
    )
    return redirect("documents_admin:edit", slug=doc.slug)
```

`documents/urls_admin.py`:

```python
"""Management routes for documents.

``documents.urls`` is mounted at ``documents/`` and so cannot host an
``admin-tools/`` path; this module is included at the root instead, the way
``admissions.urls`` owns its own ``admin-tools/web-coordinator/admit/`` route.
"""

from django.urls import path

from . import views_admin

app_name = "documents_admin"

_PREFIX = "admin-tools/web-coordinator/documents/"

urlpatterns = [
    path(_PREFIX, views_admin.index, name="index"),
    path(f"{_PREFIX}<slug:slug>/", views_admin.edit, name="edit"),
    path(f"{_PREFIX}<slug:slug>/revisions/<int:pk>/download/",
         views_admin.revision_download, name="revision_download"),
    path(f"{_PREFIX}<slug:slug>/revisions/<int:pk>/restore/",
         views_admin.restore, name="restore"),
]
```

In `config/urls.py`, beside the other root includes:

```python
    path("", include("documents.urls_admin")),
```

`documents/templates/documents/admin/index.html`:

```html
{% extends "core/staff/admin/_base.html" %}
{% block admin_heading_title %}Site documents{% endblock %}
{% block admin_kicker %}Staff · Web Coordinator{% endblock %}
{% block admin_heading %}Site documents{% endblock %}
{% block admin_intro %}Replace a document's PDF or edit how it presents. Every
save keeps the previous version, restorable from the document's page.{% endblock %}
{% block admin_sections %}
<section class="rounded-xl border border-base-300 overflow-x-auto">
  <table class="table table-sm">
    <thead>
      <tr>
        <th>Document</th><th>Category</th><th>Effective</th>
        <th>Visibility</th><th>Versions</th><th></th>
      </tr>
    </thead>
    <tbody>
      {% for d in documents %}
      <tr>
        <td class="font-medium text-base-content">{{ d.title }}</td>
        <td class="text-base-content/70">{{ d.get_category_display }}</td>
        <td class="text-base-content/70">
          {% if d.effective_date %}{{ d.effective_date|date:"M j, Y" }}
          {% else %}<span class="text-base-content/40">—</span>{% endif %}
        </td>
        <td class="text-base-content/70">
          {{ d.get_listing_visibility_display }} / {{ d.get_content_visibility_display }}
        </td>
        <td class="font-mono text-xs text-base-content/50">{{ d.revisions.count }}</td>
        <td>
          <a href="{% url 'documents_admin:edit' d.slug %}"
             class="link link-primary text-sm">Edit →</a>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

`documents/templates/documents/admin/edit.html`:

```html
{% extends "core/staff/admin/_base.html" %}
{% block admin_heading_title %}{{ doc.title }}{% endblock %}
{% block admin_kicker %}Staff · Web Coordinator · Site documents{% endblock %}
{% block admin_heading %}{{ doc.title }}{% endblock %}
{% block admin_intro %}
  <a href="{% url 'documents_admin:index' %}" class="link">← All documents</a>
  &middot;
  <a href="{{ doc.get_absolute_url }}" class="link">View the public page</a>
{% endblock %}
{% block admin_sections %}

<section class="rounded-xl border border-base-300 p-5 space-y-4">
  <h2 class="font-serif text-lg text-base-content">Edit</h2>
  <form method="post" enctype="multipart/form-data" class="space-y-4">
    {% csrf_token %}
    {% for field in form %}
    <div class="space-y-1">
      <label class="block text-sm text-base-content/80" for="{{ field.id_for_label }}">
        {{ field.label }}
      </label>
      {{ field }}
      {% if field.help_text %}
      <p class="text-xs text-base-content/55">{{ field.help_text }}</p>
      {% endif %}
      {% for error in field.errors %}
      <p class="text-xs text-error">{{ error }}</p>
      {% endfor %}
    </div>
    {% endfor %}
    {% for error in form.non_field_errors %}
    <p class="text-sm text-error">{{ error }}</p>
    {% endfor %}
    <button type="submit" class="btn btn-primary">Save changes</button>
  </form>
</section>

<section class="rounded-xl border border-base-300 p-5 space-y-3">
  <h2 class="font-serif text-lg text-base-content">Revision history</h2>
  {% if not rows %}
  <p class="text-sm text-base-content/60">
    No revisions yet. The next save will record the version in force now.
  </p>
  {% endif %}
  {% for row in rows %}
  <div class="border-t border-base-300/60 pt-3 space-y-2">
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
      <span class="text-base-content">{{ row.revision.saved_at|date:"M j, Y, g:i a" }}</span>
      <span class="text-base-content/60">
        {% if row.revision.saved_by %}{{ row.revision.saved_by.get_full_name|default:row.revision.saved_by.email }}
        {% else %}Unknown{% endif %}
      </span>
      {% if row.revision.note %}
      <span class="text-base-content/70">{{ row.revision.note }}</span>
      {% endif %}
    </div>
    {% if row.changes %}
    <ul class="text-xs text-base-content/65 space-y-1">
      {% for c in row.changes %}
      <li>
        <span class="text-base-content/80">{{ c.label }}</span>:
        {{ c.old|default:"—"|truncatechars:60 }} → {{ c.new|default:"—"|truncatechars:60 }}
      </li>
      {% endfor %}
    </ul>
    {% endif %}
    <div class="flex flex-wrap items-center gap-3">
      {% if row.revision.file %}
      <a class="link text-xs"
         href="{% url 'documents_admin:revision_download' doc.slug row.revision.pk %}">
        Download this version's PDF
      </a>
      {% endif %}
      <form method="post"
            action="{% url 'documents_admin:restore' doc.slug row.revision.pk %}">
        {% csrf_token %}
        <button type="submit" class="btn btn-ghost btn-xs">Restore this version</button>
      </form>
    </div>
  </div>
  {% endfor %}
</section>

{% endblock %}
```

- [ ] **Step 4: Run** → `uv run pytest documents -q` PASS

- [ ] **Step 5: Commit**

```bash
git add documents/views_admin.py documents/urls_admin.py documents/templates/documents/admin config/urls.py documents/test_admin_surface.py
git commit -m "feat(documents): document management under the Web Coordinator admin (task #592)"
```

---

### Task 6: Restore and download through the views

**Files:**
- Test: `documents/test_admin_surface.py` (append)

**Interfaces:**
- Consumes: `documents_admin:restore`, `documents_admin:revision_download`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_restore_view_puts_the_old_version_back(client):
    d = _doc(title="Original")
    client.force_login(_coordinator())
    url = reverse("documents_admin:edit", args=[d.slug])
    client.post(url, {"title": "Replaced", "summary": "", "description": "",
                      "notice": "", "body": "", "effective_date": "",
                      "listing_visibility": "public",
                      "content_visibility": "public",
                      "display_order": 0, "note": ""})
    d.refresh_from_db()
    assert d.title == "Replaced"
    rev = d.revisions.get()
    resp = client.post(
        reverse("documents_admin:restore", args=[d.slug, rev.pk])
    )
    assert resp.status_code == 302
    d.refresh_from_db()
    assert d.title == "Original"
    assert d.revisions.count() == 2


@pytest.mark.django_db
def test_revision_download_is_gated(client):
    d = _doc()
    rev = d.snapshot_revision()
    url = reverse("documents_admin:revision_download", args=[d.slug, rev.pk])
    client.force_login(_user())
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_revision_download_serves_the_old_pdf(client):
    d = _doc()
    rev = d.snapshot_revision()
    client.force_login(_coordinator())
    resp = client.get(
        reverse("documents_admin:revision_download", args=[d.slug, rev.pk])
    )
    assert resp.status_code == 200
    assert b"%PDF" in b"".join(resp.streaming_content)
```

- [ ] **Step 2: Run** → these should pass immediately if Task 5 is correct; if any fail, fix the view, not the test.

- [ ] **Step 3: Commit**

```bash
git add documents/test_admin_surface.py
git commit -m "test(documents): restore and revision download through the views (task #592)"
```

---

### Task 7: The public deep link and the Web Coordinator card

**Files:**
- Modify: `documents/views.py` (add `can_manage` to the detail context)
- Modify: `documents/templates/documents/detail.html`
- Modify: `core/staff.py:656-661` (`web_coordinator_admin` context)
- Modify: `core/templates/core/staff/admin/web_coordinator.html:12`
- Test: `documents/test_admin_surface.py` (append)

**Interfaces:**
- Consumes: `can_manage_documents`, `documents_admin:index`, `documents_admin:edit`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_detail_shows_no_edit_link_to_a_member(client):
    d = _doc()
    client.force_login(_user())
    body = client.get(d.get_absolute_url()).content
    assert b"Edit document" not in body


@pytest.mark.django_db
def test_detail_shows_no_edit_link_to_anonymous(client):
    d = _doc()
    body = client.get(d.get_absolute_url()).content
    assert b"Edit document" not in body


@pytest.mark.django_db
def test_detail_shows_the_edit_link_to_the_coordinator(client):
    d = _doc()
    client.force_login(_coordinator())
    body = client.get(d.get_absolute_url()).content
    assert b"Edit document" in body
    assert reverse("documents_admin:edit", args=[d.slug]).encode() in body


@pytest.mark.django_db
def test_web_coordinator_card_links_to_the_document_list(client):
    _doc()
    client.force_login(_coordinator())
    body = client.get(reverse("web_coordinator_admin")).content
    assert reverse("documents_admin:index").encode() in body
    assert b"Site documents" in body
```

- [ ] **Step 2: Run** → FAIL on the link assertions.

- [ ] **Step 3: Implement**

In `documents/views.py::detail`, add to the context dict:

```python
            "can_manage": can_manage_documents(request.user),
```

with `from .permissions import can_manage_documents` at the top.

In `documents/templates/documents/detail.html`, inside the `<nav>` at
lines 6-11, after the existing back link:

```html
    {% if can_manage %}
    <a href="{% url 'documents_admin:edit' doc.slug %}"
       class="ml-4 text-base-content/60 hover:text-primary border-b border-dotted border-base-content/40">
      Edit document
    </a>
    {% endif %}
```

In `core/staff.py::web_coordinator_admin`, add to the context:

```python
        "document_count": Document.objects.count(),
```

with `from documents.models import Document` imported inside the view
(module-level would be a cross-app import at load time).

In `core/templates/core/staff/admin/web_coordinator.html`, replace line 12:

```html
  {% url 'documents_admin:index' as documents_url %}
  {% include "core/staff/admin/_section.html" with title="Site documents" body="Replace a document's PDF or edit how it presents. Every save keeps the previous version." link_label="Manage documents" link=documents_url count=document_count count_label="documents" %}
```

- [ ] **Step 4: Run** → `uv run pytest documents core -q` PASS

- [ ] **Step 5: Commit**

```bash
git add documents/views.py documents/templates/documents/detail.html core/staff.py core/templates/core/staff/admin/web_coordinator.html documents/test_admin_surface.py
git commit -m "feat(documents): deep link from the document page, live Web Coordinator card (task #592)"
```

---

### Task 8: Django admin writes revisions too

**Files:**
- Modify: `documents/admin.py`
- Test: `documents/test_revisions.py` (append)

**Interfaces:**
- Consumes: `Document.snapshot_revision`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_admin_save_writes_a_revision(rf):
    """A PDF swapped in Django admin must land in the history too — a partial
    history is worse than none, because it is trusted."""
    from django.contrib.admin.sites import AdminSite
    from documents.admin import DocumentAdmin

    d = _doc(title="Before admin")
    admin_user = User.objects.create_superuser(email="a@x.test", password="x")
    request = rf.post("/admin/")
    request.user = admin_user

    instance = Document.objects.get(pk=d.pk)
    instance.title = "After admin"
    DocumentAdmin(Document, AdminSite()).save_model(
        request, instance, form=None, change=True,
    )

    instance.refresh_from_db()
    assert instance.title == "After admin"
    rev = instance.revisions.get()
    assert rev.title == "Before admin"
    assert rev.saved_by_id == admin_user.pk


@pytest.mark.django_db
def test_admin_create_writes_no_revision(rf):
    from django.contrib.admin.sites import AdminSite
    from documents.admin import DocumentAdmin

    admin_user = User.objects.create_superuser(email="a2@x.test", password="x")
    request = rf.post("/admin/")
    request.user = admin_user

    fresh = Document(
        title="New", slug="new-doc", category=Document.Category.REFERENCE,
        body="text",
    )
    DocumentAdmin(Document, AdminSite()).save_model(
        request, fresh, form=None, change=False,
    )
    assert fresh.revisions.count() == 0
```

- [ ] **Step 2: Run** → FAIL, the revision is not written.

- [ ] **Step 3: Implement — add to `DocumentAdmin`**

```python
    def save_model(self, request, obj, form, change):
        """Record the prior state before an admin edit.

        Deliberately unlike the staff-path rule of #485/#564: that rule stops
        admin edits from mailing members or moving money, and a snapshot does
        neither. What it prevents is a history reading "no revisions" while
        the PDF has in fact been swapped. ``save_model`` is also the one admin
        hook that knows who is acting.
        """
        if change:
            obj.snapshot_revision(user=request.user, note="Edited in Django admin")
        super().save_model(request, obj, form, change)
```

- [ ] **Step 4: Run the whole suite**

```bash
uv run pytest documents core -q
uv run ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add documents/admin.py documents/test_revisions.py
git commit -m "feat(documents): Django admin edits write revisions too (task #592)"
```

---

## Self-review

**Spec coverage.** Gate → Task 1. Model, snapshot chokepoint, `changes_against` → Task 2. Restore → Task 3. Form and its two traps → Task 4. URLs/views/templates and the `urls_admin` mounting → Task 5. Restore + download through the views → Task 6. Deep link and the Web Coordinator card → Task 7. Django-admin snapshotting → Task 8. Every "Testing" bullet in the spec maps to a named test above.

**Placeholders.** None: every step carries the code it needs.

**Type consistency.** `snapshot_revision(user=None, note="")` is called with keywords in Tasks 3, 5 and 8. `changes_against(other)` returns `list[dict]` with keys `field/label/old/new`, consumed by that name in `revision_rows` and in `edit.html`. `restore_revision(document, revision, user=None)` matches its two call sites. `SNAPSHOT_FIELDS` is defined once in `models.py` and imported by `services.py`.
