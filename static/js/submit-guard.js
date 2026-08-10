/*
 * Submit-once guard (task #545) — a form submits once.
 *
 * Costly actions on this site are synchronous POSTs behind an ordinary
 * button: sending a referral addendum mails every clinician before the
 * response comes back. That is seconds of dead time in which the button looks
 * untouched, so it gets pressed again — and the Referral Coordinator sent two
 * copies of an addendum exactly that way.
 *
 * After the first submit, further submits of that form are swallowed, every
 * submit button in it greys out, and the pressed one shows a spinner. The
 * lock ends when the page does.
 *
 * Two things here are load-bearing:
 *
 * 1. The listener is on `document`, in the bubble phase, so it runs after a
 *    form's own handler. A form whose JavaScript already called
 *    preventDefault (the Parletre chat's WebSocket path, the suggestions
 *    widget) arrives with defaultPrevented set and is left alone — the escape
 *    hatch is automatic rather than a list to maintain. A form that only
 *    *conditionally* intercepts, and this time falls through to a real POST,
 *    is guarded, which is right: that submit navigates.
 *
 * 2. It never sets the `disabled` attribute. The HTML form-submission
 *    algorithm fires `submit` *before* it builds the entry list, so disabling
 *    the pressed button inside a submit handler drops its name/value from the
 *    POST. Twenty-eight buttons here carry a name — the treasurer's
 *    approve/decline pairs, the plan queue, advancement and cartel decisions
 *    — and all of them would have posted as action-less requests. Buttons are
 *    greyed with a class (whose pointer-events:none stops the mouse) and the
 *    second submit is swallowed by a flag (which covers the keyboard, where
 *    Enter in a text field submits without touching a button at all).
 *
 * The styles live in assets/css/input.css as hand-written CSS, not Tailwind
 * utilities: the v4 build scans templates only, so a class emitted from here
 * would be stripped from the production bundle and nowhere else.
 */
(function () {
  "use strict";

  var LOCKED = "is-submitting";
  var SPINNER = "lsp-spinner";

  function submitButtons(form) {
    return form.querySelectorAll(
      "button:not([type='button']):not([type='reset']), input[type='submit']"
    );
  }

  function lock(form, pressed) {
    form.dataset.lspSubmitting = "1";
    form.setAttribute("aria-busy", "true");

    var buttons = submitButtons(form);
    for (var i = 0; i < buttons.length; i++) {
      // Every submit button, not just the pressed one: on a decision pair,
      // Approve followed quickly by Decline is worse than sending twice.
      // Links are untouched, so Cancel stays live for someone who realises
      // mid-submit that they have made a mistake.
      buttons[i].classList.add(LOCKED);
      buttons[i].setAttribute("aria-disabled", "true");
    }

    var target = pressed || buttons[0];
    if (target && target.tagName === "BUTTON" &&
        !target.querySelector("." + SPINNER)) {
      var spinner = document.createElement("span");
      spinner.className = SPINNER;
      spinner.setAttribute("aria-hidden", "true");
      target.insertBefore(spinner, target.firstChild);
    }
  }

  function unlock(form) {
    delete form.dataset.lspSubmitting;
    form.removeAttribute("aria-busy");
    var buttons = submitButtons(form);
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.remove(LOCKED);
      buttons[i].removeAttribute("aria-disabled");
    }
    var spinners = form.querySelectorAll("." + SPINNER);
    for (var j = 0; j < spinners.length; j++) {
      spinners[j].parentNode.removeChild(spinners[j]);
    }
  }

  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var form = e.target;
    if (!form || form.tagName !== "FORM") return;
    // GET forms are skipped: re-running a search or a filter costs nothing
    // and people do it deliberately.
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
    if (form.hasAttribute("data-no-submit-guard")) return;

    if (form.dataset.lspSubmitting === "1") {
      e.preventDefault();
      return;
    }
    lock(form, e.submitter);
  });

  // There is deliberately no unlock-after-N-seconds failsafe: it would re-open
  // the double-send window at precisely the moment the response is slowest,
  // which is this bug. The only reset is the back/forward cache, which
  // restores the DOM as it was left — spinner and all — and would otherwise
  // hand back a form that can never be submitted again.
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    var forms = document.querySelectorAll("form[data-lsp-submitting]");
    for (var i = 0; i < forms.length; i++) unlock(forms[i]);
  });
})();
