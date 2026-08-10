# A form submits once — the site-wide submit guard

Task #545. The Referral Coordinator clicked **Send addendum** twice and the
clinicians got two copies.

## What happened

`referrals/addendum.html` posts a plain form, and `services.send_addendum`
mails every clinician **synchronously**. On a list of thirty-six clinicians
that is seconds of dead time with no feedback: the button looks untouched, so
it gets clicked again. The second click posts the same form again, and both
POSTs run to completion — two `AddendumRecord` rows, two rounds of email.

Nothing about this is specific to addenda. Every costly action on the site is
a synchronous POST behind an ordinary button: distributing a referral,
approving a plan, comping a registration, admitting a member. The one place
that had already been bitten — the public referral request at
`accounts/templates/accounts/find_an_analyst.html` — carries a bespoke inline
"Submit-once guard" written for that form alone. This makes it the site's
behaviour instead.

## The rule

**A form submits once.** After the first submit, further submits of that form
are swallowed, every submit button in it greys out and stops responding, and
the button that was pressed shows a spinner. The lock ends when the page does.

## How

### One listener, on the document

New `static/js/submit-guard.js`, loaded `defer` from `core/base.html` beside
`flourishes.js`, unconditional — anonymous visitors post forms too (login,
signup, donate, the referral request).

It listens for `submit` on `document`, in the **bubble** phase, so it runs
after any form's own handler. That ordering is what makes the escape hatch
automatic rather than a list to maintain: a form whose JS already called
`preventDefault` — the Parlêtre chat's WebSocket path, the suggestions widget
— arrives with `event.defaultPrevented` set, and the guard leaves it alone. A
form that *conditionally* falls back to a real POST (chat with an attachment,
or a dead socket) does not set the flag, and is guarded, which is correct:
that submit navigates.

Skipped: anything but `method="post"` (re-running a search or a filter is free
and users do it deliberately), and any form carrying
`data-no-submit-guard`.

### The lock never sets the `disabled` attribute

This is the load-bearing constraint, not a style preference. The HTML form
submission algorithm fires the `submit` event **before** it constructs the
entry list, so `submitter.disabled = true` inside a submit handler silently
drops that button's `name`/`value` from the POST. Twenty-eight buttons on this
site carry a `name`: the approve/decline pairs on the treasurer's Reconcile
tab, the tuition plan queue, advancement decisions, external-analyst
decisions, cartel decisions. A guard written the obvious way would have
converted a double-send bug into a whole class of silent no-op decisions.

So the guard sets a **class** and a flag on the form, and swallows the second
submit with `preventDefault`. Serialization is never touched. The class
carries `pointer-events: none` for the mouse; the flag covers the keyboard,
where Enter in a text field submits without the button ever being pressed.

### Every submit button in the form, not just the one pressed

On a decision pair, *Approve* followed quickly by *Decline* is a worse outcome
than sending twice. `<a>` elements are untouched — a Cancel link must stay
live, since someone who realises mid-submit that they have made a mistake
should be able to leave.

### The styles are hand-written CSS

`.is-submitting` and `.lsp-spinner` go in `assets/css/input.css` beside the
`.hp-wrap` and `.lsp-lightbox` precedents. Tailwind scans
`**/templates/**/*.html` only, so a class emitted from a JS file is dropped
from the production build — the `tailwind-classes-set-in-python` gotcha in a
JS flavour, and one that fails silently and only in production. DaisyUI's own
`loading loading-spinner` is not an option for the same reason: it appears in
zero templates, so it is not in the built CSS at all.

Under `prefers-reduced-motion` the spinner slows rather than stopping. A
frozen spinner signals the opposite of what is happening.

The button grows by the spinner and its flex gap. The label is deliberately
**not** swapped for "Sending…": the width change from re-flowing text is
larger and noisier than the spinner's, and the label is what names the action
still in flight. Pinning the width exactly would mean hiding the label behind
the spinner.

### No timeout; a bfcache reset

An unlock-after-N-seconds failsafe would re-open the double-send window at
precisely the moment the response is slowest — which is this bug. The lock
therefore ends only when the page does. `pageshow` with `event.persisted`
clears it, or the back button lands on a form that can no longer be submitted.

Nothing else needs a reset: a browser-blocked `required` field never fires
`submit`, and a Django validation failure re-renders the page fresh.

### The one-off comes out

`find_an_analyst.html`'s inline guard is deleted. Left in place that form
would get both treatments — its own `disabled` + "Sending…" text swap plus the
global spinner. It is safe there today only because that form has no named
submitter, which is exactly the kind of local knowledge a site-wide rule
should retire.

## Deliberately not done

**No server-side idempotency token** (Rico, 2026-08-10). A nonce minted per
render and consumed on POST would be structurally airtight, but it is a new
mechanism across 264 forms with a failure mode of its own — a legitimate slow
submit rejected as a replay. The client-side guard closes the accidental
double-click, which is the whole of the reported problem.

## Verification

Template tests pin the script into `base.html` and both classes into
`input.css`; both are silent-failure paths, and the CSS one fails only in the
production build. Then the browser, for what tests cannot reach: the addendum
form for the reported bug, and a named-submitter decision pair to prove the
POST still carries its `decision` value.
