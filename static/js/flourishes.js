/* LSP stylistic flourishes — quiet visual gestures keyed to Lacanian themes.
 *
 * Two gestures live here today:
 *   1. The falling letter  — once per session, a randomly chosen letter
 *      in a font-serif heading detaches and floats down the page.
 *   2. Palimpsest setup    — copies the visible text of any .palimpsest
 *      element into its data-palimpsest attribute (unless one is already
 *      set) so the CSS ::before twin can render it.
 *
 * Both gestures honor `prefers-reduced-motion: reduce`.
 */
(function () {
  "use strict";

  var prefersReducedMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ----- 1. Falling letter ------------------------------------------------

  function fallingLetter() {
    if (prefersReducedMotion) return;
    if (sessionStorage.getItem("lsp-flourish-fall")) return;

    var delayMs = 8000 + Math.random() * 17000;  // 8–25s after page load
    setTimeout(detachOne, delayMs);

    function detachOne() {
      // Eligible targets: any font-serif heading currently visible.
      var headings = Array.prototype.filter.call(
        document.querySelectorAll(
          "h1.font-serif, h2.font-serif, h3.font-serif, " +
          ".dir-name.font-serif, .font-serif h1, .font-serif h2"
        ),
        isVisible
      );
      if (!headings.length) return;
      var heading = headings[Math.floor(Math.random() * headings.length)];

      // Walk text nodes inside the heading and collect characters with positions.
      var walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      var nodes = [];
      while (walker.nextNode()) {
        if (/\S/.test(walker.currentNode.textContent)) {
          nodes.push(walker.currentNode);
        }
      }
      if (!nodes.length) return;
      var node = nodes[Math.floor(Math.random() * nodes.length)];
      var text = node.textContent;
      var indices = [];
      for (var i = 0; i < text.length; i++) {
        if (/\S/.test(text[i])) indices.push(i);
      }
      if (!indices.length) return;
      var idx = indices[Math.floor(Math.random() * indices.length)];

      var before = text.slice(0, idx);
      var letter = text[idx];
      var after = text.slice(idx + 1);

      var span = document.createElement("span");
      span.className = "lsp-falling-letter";
      span.textContent = letter;

      var parent = node.parentNode;
      var beforeNode = document.createTextNode(before);
      var afterNode = document.createTextNode(after);
      parent.replaceChild(afterNode, node);
      parent.insertBefore(span, afterNode);
      parent.insertBefore(beforeNode, span);

      sessionStorage.setItem("lsp-flourish-fall", "1");
    }
  }

  function isVisible(el) {
    if (!el.getClientRects().length) return false;
    var style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    var rect = el.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
    return true;
  }

  // ----- 2. Palimpsest setup ----------------------------------------------

  function palimpsestSetup() {
    var els = document.querySelectorAll(".palimpsest");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!el.getAttribute("data-palimpsest")) {
        // Use the element's own visible text as the underlay — a literal
        // overstrike. Templates can pre-set data-palimpsest to a *different*
        // string (a French original, an earlier draft) when they want
        // translational depth instead of a simple double-strike.
        el.setAttribute("data-palimpsest", el.textContent.trim());
      }
    }
  }

  // ----- bootstrap --------------------------------------------------------

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    palimpsestSetup();
    fallingLetter();
  }
})();
