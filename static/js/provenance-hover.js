/* Treasurer payment provenance popovers (task #435).
   Promotes the CSS-hover panels to the native Popover API so they render in
   the top layer and are never clipped by the tables' overflow-x-auto wrappers.
   Without the Popover API the markup's :hover / :focus-within fallback works. */
(function () {
  "use strict";
  if (!("popover" in HTMLElement.prototype)) return;

  document.querySelectorAll("[data-prov-trigger]").forEach(function (trigger) {
    var panel = trigger.nextElementSibling;
    if (!panel || !panel.hasAttribute("data-prov-panel")) return;

    // Take over from the CSS fallback so the panel does not show twice. Remove
    // the `hidden` (display:none) class too: with the Popover API the panel's
    // own [popover]:not(:popover-open) rule hides it when closed, but a lingering
    // `hidden` would force display:none even while open, so nothing would show.
    panel.classList.remove("hidden", "group-hover:block", "group-focus-within:block");
    panel.setAttribute("popover", "manual");

    var hideTimer = null;
    function cancelHide() {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    }
    function scheduleHide() {
      cancelHide();
      hideTimer = setTimeout(function () { panel.hidePopover(); }, 120);
    }
    function show() {
      cancelHide();
      panel.style.position = "fixed";
      panel.style.margin = "0";
      if (!panel.matches(":popover-open")) {
        panel.style.left = "-9999px";
        panel.style.top = "-9999px";
        try { panel.showPopover(); } catch (e) { return; }
      }
      var t = trigger.getBoundingClientRect();
      var p = panel.getBoundingClientRect();
      var left = Math.max(8, Math.min(t.right - p.width, window.innerWidth - p.width - 8));
      var top = t.bottom + 6;
      if (top + p.height > window.innerHeight - 8) {
        top = Math.max(8, t.top - p.height - 6);
      }
      panel.style.left = left + "px";
      panel.style.top = top + "px";
    }

    trigger.addEventListener("pointerenter", show);
    trigger.addEventListener("focus", show);
    trigger.addEventListener("pointerleave", scheduleHide);
    trigger.addEventListener("blur", scheduleHide);
    panel.addEventListener("pointerenter", cancelHide);
    panel.addEventListener("pointerleave", scheduleHide);
  });
})();
