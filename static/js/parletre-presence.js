/* Parlêtre global presence heartbeat.
 *
 * Fires on every Parlêtre page so anyone with Parlêtre open registers as
 * "online now" (works on board/forum pages that have no WebSocket). Each beat
 * POSTs to the heartbeat endpoint and gets back the current roster, which it
 * renders into #parletre-online when that widget is on the page (the index). */
(function () {
  "use strict";
  var meta = document.querySelector("meta[name=csrf-token]");
  var token = meta ? meta.content : "";
  var el = document.getElementById("parletre-online");
  var list = el ? el.querySelector("[data-online-list]") : null;
  var count = el ? el.querySelector("[data-online-count]") : null;

  function render(data) {
    if (!el) return;
    var names = (data.online || []).map(function (p) { return p.name; });
    if (count) count.textContent = names.length;
    if (list) {
      list.innerHTML = "";
      names.forEach(function (n) {
        var chip = document.createElement("span");
        chip.className = "badge badge-sm badge-ghost";
        chip.textContent = n;
        list.appendChild(chip);
      });
    }
    el.hidden = names.length === 0;
  }

  function beat() {
    fetch("/parletre/heartbeat/", {
      method: "POST",
      headers: { "X-CSRFToken": token },
      credentials: "same-origin",
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) render(d); })
      .catch(function () {});
  }

  beat();
  setInterval(beat, 25000);
})();
