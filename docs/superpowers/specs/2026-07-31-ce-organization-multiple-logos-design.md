# Multiple logos per CE organization

Task #486 follow-up. 2026-07-31.

## The problem

Task #486 shipped `CEOrganization` with a single required `logo`. An accrediting
body can require more than one mark on an approved event's page, for example a
sponsor logo alongside an approved-provider seal, and one `ImageField` cannot
carry them.

Two consequences follow from the current shape. The organization is the wrong
size to hold a set, and there is **no way to change an existing organization
outside Django admin** — which contradicts the premise the feature shipped on,
that the library is faculty-managed and nobody curates it. The moment APA needs
its second mark, a self-service library becomes a Web Coordinator ticket.

## Decisions

### Logos belong to the organization, not to the event

Every event approved by a body shows that body's full logo set. The set is part
of the organization's identity, so a body requiring two marks gets both on every
page that claims it, and correcting an accreditor's branding stays a one-place
edit.

Rejected: a per-event choice of which logos to show. That would need a second
layer of checkboxes on the event edit form to serve a case we have no evidence
of. If a body ever issues genuinely event-specific marks, the answer is a second
`CEOrganization` row, not a picker.

### An organization keeps at least one logo

Removing the last logo is refused, with an error telling the user to add the
replacement first. Without the rule an organization can exist that renders
nothing but a statement, a state nobody sets out to create. Replace-the-only-logo
works as add-then-remove.

### Existing organizations get a page; the name does not get an edit field

Adding logos only at creation time would leave the first person who needs a
second APA mark stuck. So there is a per-organization page, reached from the
organization's row on the event edit page.

It edits the logo set, the URL, and the statement. **The name stays
admin-only**: it is the case-insensitive dedup key, and a rename ripples through
every event that claims the organization. Fixing a typo'd name remains a Django
admin action.

Rejected: an inline add-logo control on each organization's row of the event
edit page. It would mean a separate `<form>` per organization nested inside a
checkbox list, in a form that is not multipart, and it has nowhere to put a
Remove action.

### No reorder

`sort_order` exists so the sequence is stable and deterministic, but there is no
reorder UI. With a cap of 10 and a realistic count of two, upload order is
enough; remove-and-re-add is the escape hatch.

## Data model

New `events.CEOrganizationLogo`:

| Field | Type | Notes |
|---|---|---|
| `organization` | `FK(CEOrganization, CASCADE)` | `related_name="logos"` |
| `image` | `ImageField` | Public bucket, `upload_to="ce-organizations/"` |
| `sort_order` | `PositiveIntegerField(default=0)` | Append on add; no reorder UI |
| `created_at` | `DateTimeField(auto_now_add)` | |

Ordered by `("sort_order", "pk")`.

`CEOrganization.logo` is removed.

**Cap: 10 logos per organization**, enforced in the forms (creation counts the
uploaded files; the per-organization page counts existing + new).

One migration, three operations in order: create the model, copy each existing
organization's `logo` into a first `CEOrganizationLogo` row, drop the field. The
copy runs whether or not production has any organizations yet — it is correct
either way, and development databases do have rows.

## Editing

### Creation

The existing add-organization form on the event edit page keeps one file input
and gains an **Add another logo** button that clones the row, capped at 10. The
view reads `request.FILES.getlist("logo")`, so with JavaScript disabled the form
still works with a single logo. Every file goes through the existing
`events/ce_images.py::normalize_logo`.

### Per-organization page

New page at `/events/<slug>/ce-organizations/<pk>/`, gated by `can_edit_event`
on the event in the path. That event is provenance for the permission check and
the back link only; the organization is shared, and the page says plainly that
edits apply to every event claiming it. That warning is the one thing a faculty
member could reasonably get wrong here.

Contents: the current logos with a Remove button each, an add-more control with
the same cap and the same **Add another logo** button, and the URL and statement
fields.

Removal is its own small POST per logo, one `<form>` per row carrying the logo's
id, following the roster-remove pattern in
`workgroups/templates/workgroups/_tab_settings.html`. Adding logos and editing
the URL and statement are a second, multipart form. Two forms rather than one
so a removal never has to round-trip an unsaved file input.

## Display

`events/templates/events/_ce_credits.html` iterates `org.logos.all` inside its
existing organization loop, keeping all chips in one flat wrapping row. Two
organizations with two logos each read as four chips, which is correct: all four
are marks of bodies that approved this event, and the statements below carry the
attribution. The existing `{% if org.logo %}` guard becomes a `{% for %}` that
renders nothing when a set is empty.

The event edit page's organization rows show the same set, at the smaller chip
size already used there.

## Testing

- Logos render for an organization carrying several, on the event page and the
  Workspace Overview.
- The migration moves an existing `logo` onto a first `CEOrganizationLogo` row.
- Creation accepts several files in one post and normalizes each; more than 10
  is a form error.
- The per-organization page adds and removes logos, and refuses to remove the
  last one.
- Adding beyond the cap from the per-organization page is refused, counting
  existing logos.
- Someone who cannot edit the event in the path cannot reach or post to the
  per-organization page.
- The page edits URL and statement, and exposes no name field.

## Out of scope

- Reordering logos.
- Renaming an organization outside Django admin.
- Per-event selection of which of an organization's logos to show.
- Deleting an organization from the member-facing UI.
