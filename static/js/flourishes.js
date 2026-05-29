/* LSP stylistic flourishes — quiet visual gestures keyed to Lacanian themes.
 *
 *   1. The falling letter. A randomly chosen letter in a font-serif heading
 *      stays in place but fades to an outlined trace while a fixed-position
 *      clone of itself slides down the page — the signifier slipping the
 *      chain, leaving its silhouette. The host letter stays in text flow so
 *      nothing reflows when the gesture fires.
 *
 *   2. Overtyped correction. A word in a heading is struck through with a
 *      slow animated diagonal; the original + strike fade to a faint trace;
 *      and a (possibly substituted) word is typed letter-by-letter slightly
 *      offset above it — typewriter correction. The substitute comes from
 *      a small Lacanian/French synonym dictionary when one fits; otherwise
 *      it's the same word (a pure typewriter overstrike).
 *
 * Both gestures honor `prefers-reduced-motion: reduce`. The total number of
 * gestures per page is capped (MAX) and the two types alternate; which one
 * fires first is randomized so the rhythm isn't predictable.
 */
(function () {
  "use strict";

  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  // ----- Configuration ----------------------------------------------------

  var MAX_PER_PAGE  = 3;         // Total gestures across both types.
  var FIRST_DELAY   = 18000;     // ms before the first gesture fires.
  var FIRST_SWING   = 8000;
  var GAP           = 120000;    // ms between gestures.
  var GAP_SWING     = 30000;

  // Words → list of substitutes used by the overtype. Keyed lowercase; case is
  // preserved when applied. Multi-word entries are fine. Missing words fall
  // back to the same word (the typewriter strikes through itself).
  var SYNONYMS = {
    "directory":      ["annuaire", "registre", "index", "roster"],
    "members":        ["membres", "analysants", "sujets"],
    "events":         ["événements", "encounters", "séances", "gatherings"],
    "event":          ["événement", "encounter", "séance"],
    "calendar":       ["calendrier", "almanach", "agenda"],
    "school":         ["école", "academy", "institute"],
    "analyst":        ["analyste"],
    "analysts":       ["analystes"],
    "candidate":      ["candidat"],
    "candidates":     ["candidats"],
    "scholar":        ["érudit", "savant"],
    "scholars":       ["érudits", "savants"],
    "faculty":        ["faculté", "instructors"],
    "speakers":       ["intervenants", "voices"],
    "sessions":       ["séances"],
    "session":        ["séance"],
    "pricing":        ["tarifs", "prices"],
    "register":       ["s'inscrire", "inscribe", "enroll"],
    "registration":   ["inscription"],
    "donate":         ["donner", "contribuer", "offer"],
    "treasurer":      ["trésorier", "treasury"],
    "dashboard":      ["tableau", "control"],
    "dues":           ["cotisations"],
    "log":            ["entrer"],
    "thank":          ["merci"],
    "thanks":         ["merci"],
    "about":          ["à propos"],
    "details":        ["détails"],
    "lacanian":       ["lacanien"],
    "psychoanalysis": ["psychanalyse"],
    "coming":         ["à venir", "approaching"],
    "upcoming":       ["à venir", "approaching", "imminent"],
    "what":           ["quoi", "que"],
    "you":            ["tu", "vous"],
    "can":            ["peux", "pouvez"],
    "do":             ["faire"],
    "here":           ["ici"],
  };

  // ----- Helpers ----------------------------------------------------------

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
      var p = walker.currentNode.parentNode;
      // Skip any text inside elements our previous flourishes wrote.
      if (p && p.closest && (
            p.closest(".lsp-letter-host") ||
            p.closest(".lsp-overtype-stack"))) continue;
      if (/\S/.test(walker.currentNode.textContent)) nodes.push(walker.currentNode);
    }
    return nodes.length ? nodes[Math.floor(Math.random() * nodes.length)] : null;
  }

  function jitter(baseMs, swingMs) {
    return baseMs + (Math.random() * 2 - 1) * swingMs;
  }

  // ----- 1. Falling letter (no-reflow via fixed clone) --------------------

  function fallOne() {
    var heading = pickHeading();
    if (!heading) return false;
    var node = pickTextNode(heading);
    if (!node) return false;
    var text = node.textContent;
    var indices = [];
    for (var i = 0; i < text.length; i++) {
      if (/\S/.test(text[i])) indices.push(i);
    }
    if (!indices.length) return false;
    var idx = indices[Math.floor(Math.random() * indices.length)];

    var before = text.slice(0, idx);
    var letter = text[idx];
    var after = text.slice(idx + 1);

    // The host is a plain inline span — same width as the original character.
    // No display:inline-block, no positioning context — text flow is preserved
    // so headings don't re-wrap when the gesture fires.
    var host = document.createElement("span");
    host.className = "lsp-letter-host";
    host.textContent = letter;

    var parent = node.parentNode;
    var beforeNode = document.createTextNode(before);
    var afterNode = document.createTextNode(after);
    parent.replaceChild(afterNode, node);
    parent.insertBefore(host, afterNode);
    parent.insertBefore(beforeNode, host);

    // Measure the host's position. Force a layout read.
    var rect = host.getBoundingClientRect();
    var hostStyle = window.getComputedStyle(host);

    // The falling clone is position:fixed, drawn from the body. It doesn't
    // affect layout at all, so the host's letter (the trace) stays in place.
    var clone = document.createElement("span");
    clone.className = "lsp-falling-letter";
    clone.textContent = letter;
    clone.setAttribute("aria-hidden", "true");
    clone.style.position    = "fixed";
    clone.style.left        = rect.left + "px";
    clone.style.top         = rect.top + "px";
    clone.style.font        = hostStyle.font || (
      hostStyle.fontWeight + " " + hostStyle.fontSize + " / " +
      hostStyle.lineHeight + " " + hostStyle.fontFamily
    );
    clone.style.fontStyle   = hostStyle.fontStyle;
    clone.style.fontFeatureSettings = hostStyle.fontFeatureSettings || "normal";
    clone.style.letterSpacing = hostStyle.letterSpacing;
    clone.style.color       = hostStyle.color;
    clone.style.lineHeight  = hostStyle.lineHeight;
    document.body.appendChild(clone);

    // Pass the host's computed text color through as a CSS variable, so the
    // outline stroke keeps that color even as the fill transitions to
    // transparent (otherwise currentColor on the stroke would fade with the
    // fill and the trace would disappear).
    host.style.setProperty("--lsp-trace-color", hostStyle.color);

    // A tick later, switch the host to outline mode (so the letter reads as
    // having "left its outline behind") while the clone falls.
    setTimeout(function () { host.classList.add("is-traced"); }, 200);

    // Clean up the clone after the animation completes.
    setTimeout(function () {
      if (clone.parentNode) clone.parentNode.removeChild(clone);
    }, 6500);

    return true;
  }

  // ----- 2. Overtype with synonym substitution ----------------------------

  function applyCase(replacement, source) {
    if (source.length > 1 && source === source.toUpperCase()) {
      return replacement.toUpperCase();
    }
    if (source[0] === source[0].toUpperCase()) {
      return replacement.charAt(0).toUpperCase() + replacement.slice(1);
    }
    return replacement;
  }

  function substitute(word) {
    // Strip trailing punctuation while keeping it on the resulting string.
    var match = word.match(/^([\w’'\-]+)([^\w]*)$/);
    var bareCore = match ? match[1] : word;
    var trailing = match ? match[2] : "";
    var key = bareCore.toLowerCase();
    var options = SYNONYMS[key];
    if (!options || !options.length) return word;  // Fall back: same word.
    var pick = options[Math.floor(Math.random() * options.length)];
    return applyCase(pick, bareCore) + trailing;
  }

  function overtypeOne() {
    var heading = pickHeading();
    if (!heading) return false;
    var node = pickTextNode(heading);
    if (!node) return false;
    var text = node.textContent;

    // Pick a non-trivial word (>=3 chars so very short words don't read as glitchy).
    var matches = [];
    var re = /\S+/g;
    var m;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length >= 3) matches.push({ word: m[0], index: m.index });
    }
    if (!matches.length) return false;
    var pick = matches[Math.floor(Math.random() * matches.length)];

    var before = text.slice(0, pick.index);
    var word = pick.word;
    var after = text.slice(pick.index + word.length);
    var correctedText = substitute(word);

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

    // Variable offset per occurrence — feels less mechanical when the
    // correction lands in a different spot each time.
    var dx  = (Math.random() * 0.22 - 0.06).toFixed(3) + "em";
    var dy  = (-0.06 - Math.random() * 0.24).toFixed(3) + "em";
    var rot = (Math.random() * 2.6 - 1.3).toFixed(2) + "deg";
    corrected.style.setProperty("--ot-dx", dx);
    corrected.style.setProperty("--ot-dy", dy);
    corrected.style.setProperty("--ot-rot", rot);

    // Typing: each character animates in with a delay. Strike-draw takes
    // ~1200ms, fade takes ~600ms (overlap ~300ms), and typing starts when
    // the fade is partway through.
    for (var j = 0; j < correctedText.length; j++) {
      var ch = document.createElement("span");
      ch.className = "lsp-overtype-char";
      ch.textContent = correctedText[j];
      ch.style.animationDelay = (1500 + j * 170) + "ms";
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

    return true;
  }

  // ----- Scheduler --------------------------------------------------------

  var fired = 0;
  // Randomize whether falling letter or overtype goes first.
  var nextIsFall = Math.random() < 0.5;

  function scheduleNext(delayMs) {
    if (fired >= MAX_PER_PAGE) return;
    setTimeout(function () {
      var ok = (nextIsFall ? fallOne : overtypeOne)();
      // Don't burn the quota on a no-op (no eligible heading on this page).
      if (ok) {
        fired++;
        nextIsFall = !nextIsFall;
      }
      scheduleNext(jitter(GAP, GAP_SWING));
    }, delayMs);
  }

  function start() {
    scheduleNext(jitter(FIRST_DELAY, FIRST_SWING));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
