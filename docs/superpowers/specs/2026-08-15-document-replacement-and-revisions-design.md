# Replacing a document, and remembering what it was

Task #592. Design date: 2026-08-15.

## The problem

The board sends new formation guidelines. Today the only way to put them on
the site is the Django admin: find the `Document` row in the changelist,
upload into `file`, and remember to fix `effective_date` by hand. That path
costs two things.

**The prior file becomes unreachable.** Django has not deleted a replaced
`FileField` target since 1.3, so the old PDF is still sitting in the private
bucket under its old key—but nothing points at it, nothing records that a
swap happened, and nothing says who did it. On prod the scholar guidelines
have carried `effective_date=2023-01-09` since seeding; when the board's new
copy lands, the fact that a 2023 version was ever in force disappears with
the pointer.

**The admin is the wrong shelf.** The person holding the new PDF is looking
at `/documents/scholar-formation-guidelines/`. Asking them to change context
to a Django changelist to swap the file on the page they are already looking
at is the friction, and it is why the 2023 date has stood for three years.

`superseded_by` is not this mechanism and is not being changed. It links two
*different* `Document` rows, it is public, and across 23 production documents
it has never once been used. It answers "a different document replaced this
one"; the question here is "this document's contents changed".

## What gets built

Two things, both gated to the same pair of roles:

1. An **edit surface** reached from the document detail page, covering the
   content and presentation fields including the file.
2. A **revision history**: a full snapshot per save, visible only to those
   roles, with the prior PDF downloadable and any revision restorable.

## The gate

New `documents/permissions.py`:

```python
def can_manage_documents(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(
        user, StaffRole.WEB_DEVELOPER, StaffRole.WEB_COORDINATOR
    )
```

Shaped exactly like `suggestions.permissions.can_triage_suggestions`, which
gates on the same pair. One predicate, four call sites (the detail-page
section, the edit view, the revision download, the restore). There is no
`web_designer` StaffRole in the codebase and this task does not add one:
the Web Coordinator seat is the design seat.

Django's `is_staff` is deliberately excluded. It is the Django-admin flag,
and anyone holding it already has the admin path to the same fields; adding
it here would widen the site-facing surface for no capability gain.

## The model

`documents.DocumentRevision` — a snapshot of the state the document was in
**before** the save that created the row. So each row reads "the document
used to be this", and the current state always lives on the `Document`
itself. There is no row that duplicates the live state, and no baseline
special case on first edit.

```
document          FK Document, related_name="revisions", CASCADE
title             CharField(200)
summary           CharField(255, blank)
description       TextField(blank)
notice            CharField(500, blank)
body              TextField(blank)
file              FileField(storage=private_storage, blank)
effective_date    DateField(null, blank)
listing_visibility  CharField(16)
content_visibility  CharField(16)
display_order     IntegerField
saved_by          FK User, SET_NULL, null
saved_at          DateTimeField(auto_now_add)
note              CharField(255, blank)
Meta: ordering = ("-saved_at", "-pk")
```

The snapshot field set is exactly the editable field set, so a restore can
write every one of them back.

**The file is referenced, never copied.** `rev.file.name = doc.file.name`
assigns the storage key directly rather than uploading; two rows then point
at one S3 object, which is correct because the object is immutable once
written and nothing in this design deletes it. Copying would double the
bucket for no gain.

### Why snapshot-before rather than snapshot-after

Restoring needs the whole prior state, so a diff-only row cannot do the job.
Snapshotting *after* each save would need a synthetic baseline row for the
23 existing documents, or their original state would be unrecoverable.
Snapshotting before means the first edit captures the original for free.

"What changed in this save" is then computed, not stored:
`DocumentRevision.changes_against(other)` returns `[(field, old, new)]`, and
the view pairs each revision with its successor—the newest revision pairing
against the **live document**. That pairing is the most recent change, which
is the one a reader looks for first.

## The snapshot chokepoint

`Document.snapshot_revision(user=None, note="")` on the model, and it
**re-reads its own row from the database** rather than reading `self`:

```python
current = Document.objects.get(pk=self.pk)
```

This is not defensive habit, it is the trap this repo keeps hitting. A
`ModelForm` mutates its instance in place during validation
(`construct_instance`), which is what made `changed_reviewable_fields()`
silently wrong in #532 and what #564 had to work around by reading the
before-value ahead of binding. Re-reading makes the helper correct
regardless of when it is called, so no call site has to remember the rule.

Two call sites:

- `documents.views.document_edit`, before saving the form.
- `DocumentAdmin.save_model`, when `change` is true, with
  `user=request.user`.

**The Django admin deliberately does fire it.** This departs from the
staff-paths rule of #485/#564, and the departure is the point: that rule
exists to stop admin edits and scripts from mailing members or moving money.
A snapshot mails nobody and charges nobody. What it prevents is a history
that reads "no revisions" while the PDF has in fact been swapped—a partial
history is worse than none, because it is trusted. `save_model` is also the
one admin hook that knows `request.user`, so the "who" stays accurate.

Creating a document snapshots nothing; there is no prior state.

## Restore

`documents/services.py::restore_revision(document, revision, user)`, inside
`transaction.atomic`:

1. Snapshot the current state (note: `Before restoring the version saved
   <date>`).
2. Copy every snapshot field onto the document, `file.name` included.
3. Save and return the document.

**Forward-only**: restoring is itself an edit, so it lands in the history and
nothing is ever destroyed or rewound past. A revision is never deleted by
this feature.

## URLs, views, templates

```
documents/<slug>/edit/                          documents:edit
documents/<slug>/revisions/<int:pk>/download/   documents:revision_download
documents/<slug>/revisions/<int:pk>/restore/    documents:restore   (POST only)
```

The existing `<slug:slug>/` and `<slug:slug>/download/` patterns are
unaffected—a slug converter cannot match a path containing `/`.

`documents/detail.html` gains two blocks, both inside `{% if can_manage %}`:
a toolbar under the breadcrumb ("Edit document" + a jump to the history),
and a "Revision history" section below the content. The public "Earlier
versions" section (the `superseded_by` chain) is untouched and stays where
it is. A member or anonymous visitor sees the page exactly as it renders
today—verified by test, not by inspection.

`documents/document_edit.html` is a new full page rather than a modal: the
form carries a file input, two markdown textareas, and eight other fields,
which is too much for a dialog and too much to inline into a public
template.

## The form

`documents/forms.py::DocumentEditForm(ModelForm)` over `title`, `summary`,
`description`, `notice`, `file`, `body`, `effective_date`,
`listing_visibility`, `content_visibility`, `display_order`.

Identity fields are out of reach here and stay in Django admin: `slug` (the
URL, with no redirect if changed), `category`, `owning_workgroup`, `authors`,
`superseded_by`.

- `file` is not required, so saving without touching it keeps the current
  file; `ClearableFileInput` supplies the explicit clear.
- `display_order` is a model field with a default but without `blank=True`,
  so a `ModelForm` makes it **required**—the exact trap recorded in
  `new-modelform-field-is-required-by-default`. It gets `required=False` and
  is coerced in `clean_display_order`.
- `Document.clean()` already enforces both invariants (contents cannot be
  more public than the listing; a document needs a file or a body).
  `_post_clean` runs it, so both carry through to this form for free.
- Widget classes are `input input-bordered`, `textarea textarea-bordered`,
  `select select-bordered`, `file-input file-input-bordered`. All four
  already appear in committed templates, so Tailwind's template scan keeps
  them in the production build (`tailwind-classes-set-in-python`).

The submit-once guard (#545) applies with no opt-in, since it binds every
POST form from `base.html`.

## Testing

- **Gate**: anonymous redirects to login; a signed-in member is denied; a
  Web Developer and a Web Coordinator each reach it; a superuser reaches it.
- **Invisibility**: the detail page for a member and for an anonymous
  visitor contains no revision section and no edit link.
- **Replace**: uploading a new file writes a revision holding the *old*
  file's name while the document serves the new one, and the old file is
  still downloadable through the revision endpoint.
- **Metadata-only edit** writes a revision too.
- **Admin**: `save_model` on an existing document writes a revision stamped
  with the admin user; creating one writes none.
- **Mutation immunity**: bind a `ModelForm` to the instance, then snapshot,
  and assert the revision holds the *pre-binding* values. This is the #532
  trap pinned directly.
- **Restore** puts prior values and the prior file back, and is forward-only
  (the pre-restore state becomes a new revision).
- **Revision download** is gated by the same predicate.

## Out of scope

Backfilling synthetic revisions for the 23 existing documents; deleting or
pruning revisions; exposing any revision publicly; changing `superseded_by`;
adding a `web_designer` role; a documents console under `/admin-tools/`.
