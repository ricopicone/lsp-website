# Render Django messages once, in the base template

2026-07-31. Found while building the CE per-organization page (task #486).

## The problem

`core/templates/core/base.html` does not render Django messages. Neither does
any shared partial. Every page that wants them renders its own loop, so a view
calling `messages.success()` produces **nothing at all** unless the specific
template it lands on happens to carry that loop.

The gap is wide:

| | |
|---|---|
| `messages.*` calls across the app | 283, in 23 modules |
| Templates rendering them | 30 |

Counting templates understates the coverage a little, because five of the 30 are
section bases (`referrals/`, `availability/`, `program_admin/`,
`admissions/coordinator/`, `registrations/registrar/`) that cover whole
consoles. It understates the *gap* far more:

- **`payments/views.py` makes 89 message calls, and `payments/treasurer/base.html`
  renders none.** Only `reconcile.html`, one tab of eight, has a loop. The
  treasurer records an offline payment, waives a charge, or re-categorizes money
  and is told nothing.
- `events/event_edit.html` has no loop, so the "Changes saved." and
  "Added {org}, and applied it to this event." messages added in task #486 are
  invisible.
- `workgroups/detail.html`, `cartels`, `parletre`, and `accounts` pages are in
  the same position.

## Decision

Render messages **once**, in `core/base.html`, and delete the 30 per-page loops.

Two renderings in a single response would print every message twice, so the
deletions are not optional cleanup, they are part of the change.

Rejected: filling in the gaps template by template. It leaves 283 call sites
depending on whether someone remembered a loop in whichever template the view
happens to render, which is the defect itself rather than a fix for it.

## The canonical rendering

New `core/templates/core/_messages.html`, included from `base.html` inside
`<main>`, **above** the existing survey-nudge alert: a message responds to what
the user just did, so it belongs before standing furniture.

The 30 existing loops disagree about levels. Most branch `error` else `success`;
referrals adds `warning`; `workgroups/_tab_files.html` tests `'error' in m.tags`
and falls back to `alert-info`; and `registrations/register_confirm.html`
hardcodes `alert-error` for **every** message regardless of level.

The canonical version covers all five Django levels and matches with `in`
rather than `==`:

```html
<div role="alert" class="alert py-2 text-sm {% if 'error' in m.tags %}alert-error{% elif 'warning' in m.tags %}alert-warning{% elif 'success' in m.tags %}alert-success{% else %}alert-info{% endif %}">{{ m }}</div>
```

`in` rather than `==` because `messages.success(request, msg, extra_tags="x")`
makes `m.tags` the space-separated string `"x success"`, which `== 'success'`
silently fails to match, falling through to whatever the else branch happens to
be.

Every DaisyUI class appears literally in the template, so the Tailwind scanner
picks them up.

## Why this is safe

All 30 templates resolve to `core/base.html`, so none loses its messages:

- 27 extend `core/base.html` directly.
- `payments/treasurer/reconcile.html` extends `payments/treasurer/base.html`,
  which extends `core/base.html`.
- `workgroups/_tab_decisions.html` and `_tab_files.html` have no `{% extends %}`
  because they are includes, pulled into `workgroups/detail.html`, which extends
  `core/base.html`.

`django.contrib.messages.context_processors.messages` is already in
`config/settings/base.py`, so `messages` is in every template context.

## What this fixes beyond the stated goal

- The treasurer console gains confirmations for all 89 of its message calls.
- `register_confirm.html` stops painting success messages red.
- Any future view can call `messages.*` and have it appear, which is what the
  283 existing call sites already assume.

## Accepted cost

`workgroups/_tab_decisions.html` and `_tab_files.html` currently render messages
inside the tab panel. They will move to the top of the page, like everywhere
else. This is a visible change on pages that work today, accepted for
uniformity.

## Testing

- A message set by a view whose template had **no** loop now renders: use the
  treasurer console, the clearest instance of the bug.
- A message renders **exactly once** on a page that previously had its own loop,
  proving the deletions removed the double.
- Each level maps to its DaisyUI class, including a message carrying
  `extra_tags`, which pins the `in` versus `==` decision.
- No template still contains a messages loop, so the next person to add a page
  does not reintroduce one by copying a neighbour.

## Out of scope

- Auto-dismiss, toasts, or animation. This restores correctness, not a redesign.
- Auditing the 283 call sites for wording or level correctness.
- `core/middleware.py` and `core/staff.py`, which also call `messages.*`; they
  are covered automatically by the base rendering.
