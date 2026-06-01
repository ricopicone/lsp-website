/* Parlêtre private-chat participant picker.
 *
 * Each `.people-picker[data-search-url][data-field]` holds a chips container
 * (`[data-people-chips]`) and a search `<input>` (`[data-people-search]`).
 * Typing a name queries `data-search-url` (the member-search endpoint); choosing
 * a result adds a removable chip plus a hidden `<input name="{data-field}">` the
 * form submits. Server-rendered chips (after a validation error) are picked up
 * on load. Dropdown styling reuses `.parletre-mentions` (Tailwind doesn't scan
 * JS, so utility classes built here would be dropped from the prod CSS). */
(function () {
  "use strict";

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  function setup(host) {
    var url = host.getAttribute("data-search-url");
    var field = host.getAttribute("data-field");
    var input = host.querySelector("[data-people-search]");
    var chips = host.querySelector("[data-people-chips]");
    if (!url || !field || !input || !chips) return;

    var box = document.createElement("ul");
    box.className = "parletre-mentions";
    box.hidden = true;
    box.setAttribute("role", "listbox");
    host.style.position = "relative";
    host.appendChild(box);

    var items = [];   // current dropdown results [{id, name}]
    var active = -1;

    function selectedIds() {
      return Array.prototype.map.call(
        chips.querySelectorAll('input[type="hidden"]'),
        function (el) { return el.value; }
      );
    }

    function close() {
      box.hidden = true;
      box.innerHTML = "";
      items = [];
      active = -1;
    }

    function addChip(id, name) {
      if (selectedIds().indexOf(String(id)) !== -1) return; // no dupes
      var chip = document.createElement("span");
      chip.className = "parletre-chip";
      chip.setAttribute("data-id", id);
      chip.appendChild(document.createTextNode(name + " "));
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("data-chip-remove", "");
      btn.setAttribute("aria-label", "Remove " + name);
      btn.textContent = "×";
      chip.appendChild(btn);
      var hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = field;
      hidden.value = id;
      chip.appendChild(hidden);
      chips.appendChild(chip);
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
      addChip(it.id, it.name);
      input.value = "";
      input.focus();
      close();
    }

    var query = debounce(function (term) {
      fetch(url + "?q=" + encodeURIComponent(term), {
        headers: { "X-Requested-With": "fetch" },
      })
        .then(function (r) { return r.ok ? r.json() : { results: [] }; })
        .then(function (data) {
          var chosen = selectedIds();
          items = (data.results || []).filter(function (it) {
            return chosen.indexOf(String(it.id)) === -1;
          });
          active = items.length ? 0 : -1;
          render();
        })
        .catch(close);
    }, 150);

    input.addEventListener("input", function () {
      var term = input.value.trim();
      if (term.length < 1) { close(); return; }
      query(term);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") e.preventDefault(); // never submit from the search box
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

    input.addEventListener("blur", function () { setTimeout(close, 150); });

    // Remove a chip (server-rendered or freshly added) via event delegation.
    chips.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest("[data-chip-remove]") : null;
      if (!btn) return;
      var chip = btn.closest(".parletre-chip");
      if (chip) chip.remove();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".people-picker").forEach(setup);
  });
})();
