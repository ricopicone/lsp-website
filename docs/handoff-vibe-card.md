# Handoff: works vibe-card — avatars won't render

Status: **broken on prod**. Repeated CSS rewrites all produce
"correct-looking" HTML (verified via DevTools) but the avatar circles
don't appear visually. Fresh session needed.

## What the vibe-card is

`works/templates/works/_tone_card.html` — the fallback artwork that
renders when a `Work` has no `cover_image` uploaded. Composed in
four layers inside a 2:3 portrait box (book-cover aspect):

1. Deterministic muted background tone (color hash of title)
2. Background SVG of abstract shapes (5–9 circles/lines/rects)
3. **Author headshot avatars in the bottom-left, ~22% of card width** ← broken
4. 1–2 SVG "feature lines" overlaid on top so a line crosses through
   the avatar circle

Rendered everywhere a Work card appears:
- Catalog grid: `works/templates/works/index.html` via `_card.html`
- Detail page: `works/templates/works/detail.html`
- My works: `works/templates/works/my_works.html` via `_card.html`
- Directory profile "Selected works": `accounts/templates/accounts/directory_detail.html`

Backing helpers in `works/templatetags/works_filters.py`:
- `tone_for(title)` → hex color from title hash
- `vibe_shapes(title)` → inline SVG with deterministic abstract shapes
- `vibe_lines(title)` → inline SVG with 1–2 feature lines

## Design intent (from the user, distilled across a long thread)

- **Aspect ratio: 2:3** (classic trade-paperback book cover). NOT `aspect-square`, NOT `aspect-[3/4]` — they tried those and pushed back to "actual book cover".
- **Avatars sized as a fraction of card width** (their words: "smaller than the width ... maybe 1/3?"). I landed on 22% as a compromise.
- **Detail page cover ~ half window height** ("Maybe half window height would work"). My `min(100%, 33vh)` interpretation made it *bigger* on tall windows; current state is fixed `w-40 sm:w-48` (160/192px), modest.
- **Vibe shapes are good and working**. The user liked these.
- **Feature lines crossing through avatars** is a nice touch the user wants kept.

## What's been tried and what failed

| Commit | Approach | Result |
|---|---|---|
| `2e31b64` | Initial: w-8 h-8 (32px fixed) avatars in `flex -space-x-2`, aspect-square children | "completely missing" — user thought lost in design |
| `fe63b0e` | Square card aspect; smaller w-5 h-5 (20px) avatars; added feature lines | User: "completely missing", wants 1/3 size |
| `a493455` | Back to 2:3 aspect; `w-[22%] aspect-square` arbitrary value | Avatars sized 0 — Tailwind v4 silently dropped the classes |
| `0cb20ed` | Inline `style="width: 22%; aspect-ratio: 1;"`, kept flex | Avatars still tiny / clipped |
| `e17905a` | Added `right: 6%` to flex container for explicit width; `width: 25%` + shrink-0 on items | Visible enough to inspect → user still says missing |
| `de5b251` | Padding-bottom hack on flex items: `width: 25%; padding-bottom: 25%;` + items-end + img absolute | "Got worse / cut off" |
| `8c8e25f` | Per-avatar absolute positioning with `calc(6% + 19% * N)` left + inline `aspect-ratio: 1` | "No avatar in sight" |
| `39c444a` | Padding-top hack directly on the absolute div: `width: 22%; padding-top: 22%; height: 0;` | "Got worse" / no avatars |
| `96d90d9` (current) | Two-level nest: outer absolute (position only) → middle relative with `padding-top: 100%` (square via padding) → innermost absolute fills with image | **Last attempt, not yet eyeballed at handoff time** |

## Hypotheses for the next session

The user provided this DevTools `outerHTML` after commit `39c444a`
(padding-top hack on the absolute div). The HTML looked correct but
**no avatar was rendering**. This is the key clue:

```html
<div class="relative w-full rounded-md overflow-hidden"
     style="aspect-ratio: 2/3; background-color: #7a98a3;">
  <svg viewBox="0 0 100 100" preserveAspectRatio="none"
       class="absolute inset-0 w-full h-full pointer-events-none">
    <!-- vibe shapes -->
  </svg>
  <div class="absolute"
       style="bottom: 6%; left: calc(6% + 19% * 0); width: 22%; padding-top: 22%; height: 0; z-index: 11;">
    <div class="absolute inset-0 rounded-full overflow-hidden ring-1 ring-base-100/80">
      <img src="https://lsp-website-media-uswest2.s3.amazonaws.com/headshots/2026/info_at_lrrtherapy.com.jpg"
           alt="" class="w-full h-full object-cover">
    </div>
  </div>
  <svg viewBox="0 0 100 100" preserveAspectRatio="none"
       class="absolute inset-0 w-full h-full pointer-events-none">
    <!-- feature lines -->
  </svg>
</div>
```

The image URL fetches OK (verified via curl). The styles are inline
(no Tailwind generation question). So why isn't it rendering?

**Untested hypotheses, ordered by likelihood:**

1. **`padding-top: 22%` on a position-absolute div doesn't compute height
   the way I expect.** Per CSS spec, padding percentages reference
   containing-block inline size. For an absolutely-positioned element,
   the containing block is the *padding box* of the nearest positioned
   ancestor (the tone-card div). Tone-card width = card width. So
   padding-top: 22% should = 22% of card width.

   **But maybe browsers are giving padding-top: 22% relative to
   the element's *own* width (a different spec interpretation), which
   would still be square but a different size.** Either way the avatar
   should be visible — but check actual computed `padding-top` in pixels.

   The latest commit (`96d90d9`) puts the padding-top on a *non-positioned*
   middle div, which is the canonical pattern. **The next session
   should verify this commit first before assuming it still fails.**

2. **`bottom: 6%` on the absolute child isn't resolving because the
   parent's height is derived from `aspect-ratio`, not declared.**
   Percentage offsets (top/bottom) reference containing-block height.
   If the browser doesn't treat aspect-ratio-derived height as a
   "specified" height for percentage resolution, `bottom: 6%` could
   collapse to 0 or auto. Mostly fixable in modern browsers but worth
   confirming with DevTools computed style.

3. **The image *is* loading and positioned correctly, but is being
   visually clipped by overflow:hidden somewhere.** The tone-card has
   `overflow-hidden`. If `bottom: 6%` is being misinterpreted such that
   the avatar div is positioned with its top at `bottom: 6%` (instead
   of its bottom), it would be below the visible card area and clipped.

4. **z-index stacking.** Avatar has `z-index: 11`; both SVGs have
   `z-index: auto`. The feature-lines SVG (rendered last in DOM with
   `pointer-events-none` and z-index auto) *should* paint below the
   avatar (z 11 > z auto in same stacking context). But edge cases
   exist. Trying `z-index: 50` on the avatar would test this.

5. **The img is loading but its parent dimensions are zero.** `class="w-full h-full"` on the img requires its parent (the inner
   `<div class="absolute inset-0 rounded-full ...">`) to have a known
   non-zero size. That inner div is `absolute inset-0` inside the outer
   positioned div whose padding-box should be 22% × 22%. **If the
   outer div has actual height 0 (because `aspect-ratio` and
   `padding-top` aren't producing the expected dimension), the inner
   `inset-0` would be 0×0 too**, and the img would render 0×0.

## Suggested next-session actions

1. **First: ask the user if commit `96d90d9` (latest) fixed it.** That
   commit moved the padding-top hack into a nested non-positioned div,
   which is the standard Bootstrap-style aspect-ratio shim. It may
   already be solved.

2. **If still broken: get the computed style.** Ask the user to open
   DevTools, click on the outer avatar div (the one with
   `style="bottom: 6%; ..."`), and paste the *Computed* tab values for:
   - `width`, `height`, `top`, `bottom`, `left`, `right`, `padding-top`
   - Same for the inner `<div class="absolute inset-0 ...">`
   - And for the `<img>` inside that
   These will reveal whether the box is sized correctly or collapsed.

3. **If padding-top isn't computing right, try a completely different
   approach: SVG-embedded avatars.** Put the avatar circles inside the
   `vibe_shapes` SVG using `<image href>` + `<clipPath circle>`. SVG
   coordinates are 100% predictable (viewBox 0–100), no CSS cascade.
   But the parent SVG has `preserveAspectRatio="none"` for the rect-y
   vibe shapes — embedding avatars there would stretch them. Would need
   a *separate* SVG element with `preserveAspectRatio="xMidYMid meet"`
   positioned absolutely.

4. **Or: just give up on percentage sizing and use fixed pixels.**
   `<div class="absolute" style="bottom: 8px; left: 8px;">` with
   `<img class="w-12 h-12 rounded-full object-cover">` (48px). On a
   240px card it's 20% (close to user's target). On a 160px card
   (mobile) it's 30%. Loses the responsive proportion but at least
   *renders*. Could parameterize with a different fixed size per
   breakpoint.

## Things to NOT touch

- `tone_for` / `vibe_shapes` / `vibe_lines` in `works_filters.py` —
  those work fine, user likes them.
- `aspect-ratio: 2/3` on the outer tone-card — that's working.
- Newsletter/Document app — separate from this, working on prod.
- Multi-PDF WorkFile schema — working, just doesn't interact with
  vibe-cards.

## Gotchas to remember (in `~/.claude/.../memory/`)

- **Django `{# … #}` comments are single-line only**. Multi-line ones
  leak as visible page text. Use `{% comment %} … {% endcomment %}`
  for anything that doesn't end on its opening line. **I hit this 4×
  in one session.** Recommend the new session refuse to ever type `{#`
  without immediately typing `#}` on the same line.
- **Tailwind v4 silently drops arbitrary-value classes containing `/`
  or `%`** — `aspect-[2/3]`, `w-[22%]`, `bottom-[6%]` don't generate
  any CSS. `min-w-[16rem]`, `max-w-[12rem]` work fine (length values
  with rem are OK). The v4 docs say `aspect-[2/3]` should work but in
  this project's build it doesn't. Workaround: inline styles for
  ratio/percentage values, or use predefined fractional classes
  (`w-1/4`, `w-1/5`).

## File map

- `works/templates/works/_tone_card.html` — the vibe-card itself
- `works/templates/works/_card.html` — catalog card wrapper (uses tone-card as fallback)
- `works/templates/works/detail.html` — detail page (renders cover/tone-card at top of header)
- `works/templates/works/index.html` — catalog grid
- `works/templatetags/works_filters.py` — `tone_for`, `vibe_shapes`,
  `vibe_lines`
- `works/models.py` — `Work`, `WorkFile`, `WorkAuthor`

## Deploy notes

- All changes ship via push to `main` → GHA → SSM → EC2.
- After every push, allow ~2–3 min for deploy + Docker rebuild before
  refreshing the prod page. (My re-pushes got conflated in user
  feedback because of this.)
- Prod URL: `https://app.lacanschool.org/works/palimpsest-a-voice/`
  (Laura Rivera Rodríguez's Palimpsest — currently the only Work
  in prod, so the obvious test case).

## Other context the next session needs

- See `CLAUDE.md` at the repo root for project orientation.
- The `documents` and `works` apps were both built this session.
  Everything else (governance docs, newsletters, Palimpsest seed,
  multi-PDF schema, two-axis visibility, DocumentAuthor M2M, notice
  field on Style Guide) is shipped and working.
- The autonomous run got most of the user's punchlist done; the
  vibe-card avatars are the one remaining issue.
