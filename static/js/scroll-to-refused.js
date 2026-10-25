/*
 * A refused form re-renders its page from the top while the errors sit
 * further down, so the page looked unchanged and unsaved (task #820, the #817
 * lesson). The server marks the refused form, or its error summary, with
 * `data-scroll-here`; this brings the first such element into view.
 */
(function () {
  "use strict";
  function go() {
    var el = document.querySelector("[data-scroll-here]");
    if (el) el.scrollIntoView({ block: "start" });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", go);
  } else {
    go();
  }
})();
