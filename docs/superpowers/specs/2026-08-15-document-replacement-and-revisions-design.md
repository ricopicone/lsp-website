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

**There is no site-side surface for it at all.** Documents are the one piece
of editable site content with no home under `/admin-tools/`. The Web
Coordinator admin has been holding a slot for them since it was built—
`core/templates/core/staff/admin/web_coordinator.html:12` renders a *Planned*
card reading "Site documents: manage shared documents and downloads surfaced
across the site." This task fills that slot.

`superseded_by` is not this mechanism and is not being changed. It links two
*different* `Document` rows, it is public, and across 23 production documents
it has never once been used. It answers "a different document replaced this
one"; the question here is "this document's contents changed".

## What gets built

A **role-based** surface, matching how every other admin area here is
organised—by the role that owns the work, not by the object being worked on:

1. `/admin-tools/web-coordinator/documents/` — the document list, replacing
   the *Planned* card on the Web Coordinator admin.
2. `/admin-tools/web-coordinator/documents/<slug>/` — the edit page for one
   document: every content and presentation field including the file, with
   that document's **revision history** below it.
3. A single gated **"Edit" deep link** on the public document detail page,
   so that reading a document and fixing it stay one click apart.

Putting the history on the admin page rather than the public one makes the
invisibility requirement structural: no gated block renders in
`documents/detail.html` at all beyond that one link, so there is no
`{% if %}` for a later edit to get wrong.

## The gate

New `documents/permissions.py`:

```python
def can_manage_documents(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR)
```

The surface belongs to the role that owns it, matching `direct_admit` and
the aphorism manager, the two tools already living on that page. Superusers
pass implicitly, as they do for every `StaffRole`. The Web Developer is
deliberately *not* in this gate: the parent hub page is
`staff_role_required(WEB_COORDINATOR)`, so a paired gate would grant a role
access to a child page while 403-ing it on the parent—an incoherence, and
the Web Developer already holds the Django admin path to the same fields.

Django's `is_staff` is excluded for the same reason it is everywhere else
here: it is the Django-admin flag, not a school role.

One predicate, and one decorator over it in the same module:

```python
def manage_documents_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not can_manage_documents(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return _wrapped
```

Anonymous visitors bounce to login and return; a signed-in non-holder gets a
403. Same shape as `core.access._guard`, but expressed over this app's own
predicate so the template flag and the view gate cannot drift apart.

## The model

`documents.DocumentRevision` — a snapshot of the state the document was in
**before** the save that created the row. So each row reads "the document
used to be this", and the current state always lives on the `Document`
itself. There is no row duplicating the live state, and no baseline special
case on first edit.

```
document            FK Document, related_name="revisions", CASCADE
title               CharField(200)
summary             CharField(255, blank)
description         TextField(blank)
notice              CharField(500, blank)
body                TextField(blank)
file                FileField(storage=private_storage, blank)
effective_date      DateField(null, blank)
listing_visibility  CharField(16)
content_visibility  CharField(16)
display_order       IntegerField
saved_by            FK User, SET_NULL, null
saved_at            DateTimeField(auto_now_add)
note                CharField(255, blank)
Meta: ordering = ("-saved_at", "-pk")
```

The snapshot field set is exactly the editable field set, so a restore can
write every one of them back.

**The file is referenced, never copied.** Assigning the storage key
(`rev.file = doc.file.name`) sets the name without re-uploading, so two rows
point at one S3 object. That is correct because the object is immutable once
written and nothing in this design deletes it. Copying would double the
bucket for no gain.

### Why snapshot-before rather than snapshot-after

Restoring needs the whole prior state, so a diff-only row cannot do the job.
Snapshotting *after* each save would need a synthetic baseline row for the
23 existing documents, or their original state would be unrecoverable.
Snapshotting before means the first edit captures the original for free.

"What changed in this save" is then computed, not stored:
`DocumentRevision.changes_against(other)` returns a list of
`{field, label, old, new}`, and the view pairs each revision with its
successor—the newest revision pairing against the **live document**. That
pairing is the most recent change, which is the one a reader looks for first.

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

- `documents.views_admin.document_edit`, before saving the form.
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

1. Snapshot the current state, noted `Before restoring the version saved
   <date>`.
2. Copy every snapshot field onto the document, the file name included.
3. Save and return the document.

**Forward-only**: restoring is itself an edit, so it lands in the history and
nothing is destroyed or rewound past. A revision is never deleted here.

## URLs, views, templates

`documents.urls` is mounted at `documents/`, so it cannot host an
`admin-tools/` path. The management routes get their own module,
`documents/urls_admin.py` (`app_name = "documents_admin"`), included at the
root in `config/urls.py` beside `admissions.urls`—which owns its own
`admin-tools/web-coordinator/admit/` route the same way.

```
admin-tools/web-coordinator/documents/                      documents_admin:index
admin-tools/web-coordinator/documents/<slug>/               documents_admin:edit
admin-tools/web-coordinator/documents/<slug>/revisions/<pk>/download/
                                                            documents_admin:revision_download
admin-tools/web-coordinator/documents/<slug>/revisions/<pk>/restore/
                                                            documents_admin:restore  (POST)
```

Views live in `documents/views_admin.py`, following the
`registrations/views_admin.py` console precedent. Templates go under
`documents/templates/documents/admin/`, extending
`core/staff/admin/_base.html` so the new pages inherit the admin chrome.

`core/staff.py::web_coordinator_admin` gains a `document_count` for the card;
`web_coordinator.html:12` swaps its *Planned* placeholder for a real link.

`documents/detail.html` gains exactly one block, inside
`{% if can_manage %}`: a small "Edit document" link beside the breadcrumb.
`documents.views.detail` supplies the flag. The public "Earlier versions"
section (the `superseded_by` chain) is untouched.

## The form

`documents/forms.py::DocumentEditForm(ModelForm)` over `title`, `summary`,
`description`, `notice`, `file`, `body`, `effective_date`,
`listing_visibility`, `content_visibility`, `display_order`, plus a
non-model `note` field for the history entry.

Identity fields stay in Django admin: `slug` (the URL, with no redirect if
changed), `category`, `owning_workgroup`, `authors`, `superseded_by`.

- `file` is not required, so saving without touching it keeps the current
  file; `ClearableFileInput` supplies the explicit clear.
- `display_order` is a model field with a default but without `blank=True`,
  so a `ModelForm` makes it **required**—the exact trap recorded in
  `new-modelform-field-is-required-by-default`. It gets `required=False` and
  is coerced in `clean_display_order`.
- `Document.clean()` already enforces both invariants (contents cannot be
  more public than the listing; a document needs a file or a body).
  `_post_clean` runs it, so both carry through for free.
- Widget classes are `input input-bordered`, `textarea textarea-bordered`,
  `select select-bordered`, `file-input file-input-bordered`. All four
  already appear in committed templates, so Tailwind's template scan keeps
  them in the production build (`tailwind-classes-set-in-python`).

The submit-once guard (#545) applies with no opt-in, since it binds every
POST form from `base.html`.

## Testing

- **Gate**: anonymous redirects to login; a signed-in member gets 403; a Web
  Coordinator and a superuser each reach the list and the edit page; a Web
  Developer without the Coordinator role does **not**.
- **Invisibility**: the detail page for a member and for an anonymous
  visitor contains no edit link and no revision markup.
- **Replace**: uploading a new file writes a revision holding the *old*
  file's name while the document serves the new one, and the old file is
  still downloadable through the revision endpoint.
- **Metadata-only edit** writes a revision too.
- **Admin**: `save_model` on an existing document writes a revision stamped
  with the admin user; creating one writes none.
- **Mutation immunity**: bind a `ModelForm` to the instance, then snapshot,
  and assert the revision holds the *pre-binding* values. The #532 trap,
  pinned directly.
- **Restore** puts prior values and the prior file back, and is forward-only
  (the pre-restore state becomes a new revision).
- **Revision download** is gated by the same predicate.
- **The Web Coordinator card** links to the list rather than reading
  "Planned".

## Out of scope

Backfilling synthetic revisions for the 23 existing documents; deleting or
pruning revisions; exposing any revision publicly; changing `superseded_by`;
adding a `web_designer` role; creating documents from this surface (Django
admin still owns creation, since slug and category live there).
