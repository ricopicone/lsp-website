/* LSP stylistic flourishes — quiet visual gestures keyed to Lacanian themes.
 *
 *   1. The falling letter. Every ~2 minutes (±30s), a randomly chosen letter
 *      in a font-serif heading detaches and floats down the page. An outlined
 *      ghost of the letter remains in its place — a trace of the signifier
 *      that fell out of the chain. Repeats; outlines accumulate.
 *
 *   2. Overtyped correction. Every ~2 minutes (±30s), offset from the falling
 *      schedule, a word in a heading gets struck through with a single
 *      animated diagonal, fades, and the original word is "retyped" slightly
 *      offset above it letter-by-letter — like a typewriter correction.
 *
 * Both gestures honor `prefers-reduced-motion: reduce`.
 */
(function () {
  "use strict";

  var prefersReducedMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (prefersReducedMotion) return;  // No motion-based flourishes.

  // Common: pick a random visible heading, optionally a random word/letter inside.

  var HEADING_SELECTOR =
    "h1.font-serif, h2.font-serif, h3.font-serif, " +
    ".dir-name.font-serif, .font-serif h1, .font-serif h2";

  function pickHeading() {
    var hs = Array.prototype.filter.call(
      document.querySelectorAll(HEADING_SELECTOR),
      isVisible
    );
    return hs.length ? hs[Math.floor(Math.random() * hs.length)] : null;
  }

  function isVisible(el) {
    if (!el.getClientRects().length) return false;
    var style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    var rect = el.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
    return true;
  }

  function pickTextNode(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) {
      // Skip text inside elements we wrote (avoid stacking flourishes on flourishes).
      var p = walker.currentNode.parentNode;
      if (p && p.closest && (p.closest(".lsp-letter-fall-container") || p.closest(".lsp-overtype-stack"))) {
        continue;
      }
      if (/\S/.test(walker.currentNode.textContent)) {
        nodes.push(walker.currentNode);
      }
    }
    return nodes.length ? nodes[Math.floor(Math.random() * nodes.length)] : null;
  }

  function jitter(baseMs, swingMs) {
    return baseMs + (Math.random() * 2 - 1) * swingMs;
  }

  function repeatEvery(fn, baseMs, swingMs, firstDelayMs) {
    function loop() {
      try { fn(); } catch (_) { /* swallow; never break the page */ }
      setTimeout(loop, jitter(baseMs, swingMs));
    }
    setTimeout(loop, firstDelayMs);
  }

  // ----- 1. Falling letter w/ outlined trace ------------------------------

  function fallOne() {
    var heading = pickHeading();
    if (!heading) return;
    var node = pickTextNode(heading);
    if (!node) return;
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

    var container = document.createElement("span");
    container.className = "lsp-letter-fall-container";

    var trace = document.createElement("span");
    trace.className = "lsp-letter-trace";
    trace.textContent = letter;
    trace.setAttribute("aria-hidden", "true");

    var falling = document.createElement("span");
    falling.className = "lsp-falling-letter";
    falling.textContent = letter;

    container.appendChild(trace);
    container.appendChild(falling);

    var parent = node.parentNode;
    var beforeNode = document.createTextNode(before);
    var afterNode = document.createTextNode(after);
    parent.replaceChild(afterNode, node);
    parent.insertBefore(container, afterNode);
    parent.insertBefore(beforeNode, container);
  }

  // ----- 2. Overtype correction -------------------------------------------

  function overtypeOne() {
    var heading = pickHeading();
    if (!heading) return;
    var node = pickTextNode(heading);
    if (!node) return;
    var text = node.textContent;

    // Choose a word — a run of non-space chars surrounded by space or boundary.
    var matches = [];
    var re = /\S+/g;
    var m;
    while ((m = re.exec(text)) !== null) matches.push({ word: m[0], index: m.index });
    if (!matches.length) return;
    var pick = matches[Math.floor(Math.random() * matches.length)];

    var before = text.slice(0, pick.index);
    var word = pick.word;
    var after = text.slice(pick.index + word.length);

    // Build: <span.stack><span.base>word</span><span.strike></span><span.new>word*</span></span>
    var stack = document.createElement("span");
    stack.className = "lsp-overtype-stack";

    var base = document.createElement("span");
    base.className = "lsp-overtype-base";
    base.textContent = word;

    var strike = document.createElement("span");
    strike.className = "lsp-overtype-strike";
    strike.setAttribute("aria-hidden", "true");

    var corrected = document.createElement("span");
    corrected.className = "lsp-overtype-new";
    corrected.setAttribute("aria-hidden", "true");
    // Letter-by-letter typing: each char a span with a delay
    for (var j = 0; j < word.length; j++) {
      var ch = document.createElement("span");
      ch.className = "lsp-overtype-char";
      ch.textContent = word[j];
      // Strike fully draws first (~600ms) then fades (~200ms), then types.
      ch.style.animationDelay = (900 + j * 55) + "ms";
      corrected.appendChild(ch);
    }

    stack.appendChild(base);
    stack.appendChild(strike);
    stack.appendChild(corrected);

    var parent = node.parentNode;
    var beforeNode = document.createTextNode(before);
    var afterNode = document.createTextNode(after);
    parent.replaceChild(afterNode, node);
    parent.insertBefore(stack, afterNode);
    parent.insertBefore(beforeNode, stack);
  }

  // ----- bootstrap --------------------------------------------------------

  function start() {
    // Stagger schedules so the two gestures don't pile up.
    repeatEvery(fallOne,     120000, 30000,  20000); // first ~20s, then every ~120±30s
    repeatEvery(overtypeOne, 120000, 30000,  80000); // first ~80s, offset by ~60s
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
