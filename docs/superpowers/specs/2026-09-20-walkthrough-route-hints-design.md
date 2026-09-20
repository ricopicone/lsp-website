# Walkthrough route hints: showing the way, not just the door

**Task #749 follow-up. Status: design for review (not built).**

## The problem

A walkthrough step today is a destination. "Open the Roster tab" is a link
straight to `/groups/<slug>/?tab=roster`, so the member arrives without ever
learning that the Roster tab lives on their seminar's Workspace, which lives
under My LSP → Groups, which lives in the avatar menu. Rico's dry run named
this exactly: the links are "a direct link to where they want to go instead
of showing them how to navigate the nav, tabs, menus". The walkthrough gets
them there once and teaches nothing they can repeat.

The site already has a hint mechanism (`core/_tour_hint.html` +
`window.lspTourHint` in `base.html`): a pulsing anchor and a popover with a
"Got it" button, driven by `ChecklistTask.hint_selector` / `hint_text`. It has
three limits, all structural:

1. **One hint per step**, on one page. A step whose route crosses four pages
   can describe only the last of them.
2. **Wired by hand into each template.** Three pages include the partial
   today, each gated by its own "is this the right page" check. Every new hint
   is an edit to a feature template.
3. **Dismissed forever on first click** (`localStorage`), with no relation to
   the step being done. A member who dismisses the hint on the wrong page
   never sees it again on the right one.

## The design

### A step carries a route

A route is an ordered list of hops. Each hop says *on which page* it applies,
*what to point at*, and *what to say*:

```python
@dataclass(frozen=True)
class Hop:
    page: str          # a path pattern the current request must match
    selector: str      # CSS selector of the element to pulse
    text: str          # one sentence, HTML allowed, no markdown
    placement: str = "below"
```

`ChecklistTask` gains `route: tuple[Hop, ...] = ()`. The existing single
`hint_*` fields become the degenerate one-hop case and are kept for the three
walkthroughs that use them; a step may have a route or a hint, not both.

Example, "Open the Roster tab":

| Page | Points at | Says |
| --- | --- | --- |
| any page | the avatar button | Open your menu. |
| any page with the menu open | My LSP → Groups | Your seminars are under My LSP, Groups. |
| `/formation/?tab=groups` | the viewer's seminar card | This is your seminar. Open it. |
| `/groups/<slug>/` (Overview) | the Roster tab | Your roster, approvals, and codes are on this tab. |

`page` is matched against `request.path` plus query, using the same
`resolve_url` machinery the step already has so the seminar slug is the
viewer's own. A hop with `page="*"` matches everywhere and is the fallback
when no more specific hop matches: on a page off the route, the member is
pointed back at the menu.

### The base template renders the current hop

`base.html` already renders the card for the active walkthrough. It gains one
more block: for the **first unfinished step**, find the first hop whose page
matches the current request, and render `_tour_hint.html` for it. The three
hand-wired includes are removed once their walkthroughs are converted, so a
new hint is a data change in `core/checklists.py` and nothing else.

Only the first unfinished step gets a hop. Two pulsing elements on one page
is noise, and the card already orders the steps.

### Anchors are data attributes, not classes

Hints today target CSS classes and ids that exist for styling
(`#choose-photo`, `.parletre-composer`). Those move under a refactor and the
hint silently stops matching. Route hops target `data-tour="…"` attributes
added for this purpose and for nothing else:

| Anchor | Where |
| --- | --- |
| `data-tour="avatar"` | the header avatar button |
| `data-tour="my-lsp-<tab>"` | each My LSP deep link in the avatar menu and each tab on the hub |
| `data-tour="group-card"` + `data-tour-slug` | each card on My LSP → Groups |
| `data-tour="ws-tab-<key>"` | each Workspace tab |
| `data-tour="edit-event"`, `"generate-code"`, `"joining-instructions"`, `"registration-status"` | the faculty tools panel |
| `data-tour="meet-system-check"` | the Meet tab's test link |

A hop whose selector matches nothing renders nothing. No error, no popover
floating in space.

### Dismissal belongs to the hop and the step

A "Got it" dismisses that hop for the session (`sessionStorage`, keyed by
walkthrough, step, and hop index), not forever. When the step ticks, all its
hops are moot because the step is no longer first-unfinished. Restarting the
walkthrough clears hop dismissals along with the ticks it already clears.

The pulse and popover appear after the same 600 ms beat the current hint
uses, and never on a page where the card is minimized: a minimized card means
"not now".

### Visit-ticking and routes agree

A step that ticks on visit (`visit_ticks`) is done the moment its final hop's
page is reached, so the route ends where the tick fires. Nothing new is
needed for that: the tick runs first, the step stops being first-unfinished,
and the hop renderer moves on to the next step.

## What this is not

- **Not a guided tour that drives the page.** The member clicks; the site
  points. No hop ever opens a menu or changes a tab for them.
- **Not a replacement for the step link.** The link stays as the shortcut for
  someone who already knows the way.
- **Not for every walkthrough at once.** Convert the faculty walkthrough
  first, since it is the one with a real route problem; the profile, Parlêtre,
  and seminar walkthroughs keep their single hint until someone has a reason
  to convert them.

## Testing

- `core/test_checklists.py`: a route's hops resolve their page pattern against
  the viewer's own offering; `page="*"` is the fallback; a step with both
  `route` and `hint_selector` is refused at construction.
- `core/test_preview_tour.py`: the base template renders exactly one hop for
  the first unfinished step; a page off the route renders the fallback hop;
  a finished step renders no hop; a minimized card renders no hop.
- Template tests pin the `data-tour` anchors on the avatar, the My LSP tabs,
  the group cards, and the Workspace tabs, so a refactor that drops one fails
  in CI rather than in a training.
- Browser check on prod: walk the Roster-tab route from the guide page with
  the card open, confirming the pulse moves from avatar → menu → card → tab.

## Effort

About a day: the `Hop` dataclass and matcher (2 h), the base-template
renderer and dismissal (2 h), anchors across six templates (2 h), converting
the faculty walkthrough's eight steps to routes (1 h), tests and a browser
pass (2 h).
