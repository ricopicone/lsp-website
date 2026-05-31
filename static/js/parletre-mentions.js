/* Parlêtre @mention autocomplete.
 *
 * Progressive enhancement: each composer textarea is wrapped in a
 * `.mention-host[data-mention-url]`. Type "@" + a name and a dropdown of
 * matching members appears; choosing one inserts the directory-slug token
 * (`@first-last`) that the server resolves into a mention notification.
 * With JS off, members can still type the token by hand. */
(function () {
  "use strict";
  var TOKEN_RE = /@([\w.\-]*)$/; // the @token immediately before the caret

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  function setup(host) {
    var textarea = host.querySelector("textarea");
    var url = host.getAttribute("data-mention-url");
    if (!textarea || !url) return;

    // Styled by .parletre-mentions in assets/css/input.css (not Tailwind
    // utilities — Tailwind doesn't scan JS, and the prod CSS build only sees
    // template dirs, so utility classes built here would be dropped).
    var box = document.createElement("ul");
    box.className = "parletre-mentions";
    box.hidden = true;
    box.setAttribute("role", "listbox");
    host.style.position = "relative";
    host.appendChild(box);

    var items = [];   // [{slug, name}]
    var active = -1;
    var matchStart = -1;

    function close() {
      box.hidden = true;
      box.innerHTML = "";
      items = [];
      active = -1;
      matchStart = -1;
    }

    function render() {
      box.innerHTML = "";
      items.forEach(function (it, i) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.textContent = it.name;
        if (i === active) a.className = "is-active";
        a.addEventListener("mousedown", function (e) {
          e.preventDefault();
          choose(i);
        });
        li.appendChild(a);
        box.appendChild(li);
      });
      box.hidden = items.length === 0;
    }

    function choose(i) {
      var it = items[i];
      if (!it) return;
      var value = textarea.value;
      var caret = textarea.selectionStart;
      var before = value.slice(0, matchStart);
      var after = value.slice(caret);
      var insert = "@" + it.slug + " ";
      textarea.value = before + insert + after;
      var pos = before.length + insert.length;
      textarea.setSelectionRange(pos, pos);
      textarea.focus();
      close();
    }

    var query = debounce(function (term) {
      fetch(url + "&q=" + encodeURIComponent(term), {
        headers: { "X-Requested-With": "fetch" },
      })
        .then(function (r) { return r.ok ? r.json() : { results: [] }; })
        .then(function (data) {
          items = data.results || [];
          active = items.length ? 0 : -1;
          render();
        })
        .catch(close);
    }, 150);

    textarea.addEventListener("input", function () {
      var upto = textarea.value.slice(0, textarea.selectionStart);
      var m = upto.match(TOKEN_RE);
      if (!m) { close(); return; }
      matchStart = textarea.selectionStart - m[0].length;
      var term = m[1];
      if (term.length < 1) { close(); return; } // wait for at least one char
      query(term);
    });

    textarea.addEventListener("keydown", function (e) {
      if (box.hidden || !items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault(); active = (active + 1) % items.length; render();
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); active = (active - 1 + items.length) % items.length; render();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault(); choose(active);
      } else if (e.key === "Escape") {
        close();
      }
    });

    textarea.addEventListener("blur", function () { setTimeout(close, 150); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".mention-host").forEach(setup);
  });
})();
