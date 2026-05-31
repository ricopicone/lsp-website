/* Parlêtre realtime chat (M13.5b) + iMessage-style composer.
 *
 * WebSocket: open a socket to the channel, append broadcast messages live,
 * and send the composer over it instead of reloading. With JS/WS unavailable
 * the form posts normally (server still broadcasts to live clients). Posts
 * with file attachments fall back to the multipart form. Bodies are sanitised
 * server-side, so inserting body_html as HTML is safe.
 *
 * Composer: Enter sends, Shift+Enter inserts a newline; the textarea
 * auto-grows; a paperclip opens the hidden file input and shows the picked
 * files; the round ↑ button submits. */
(function () {
  "use strict";
  var root = document.querySelector("[data-chat]");
  if (!root || !("WebSocket" in window)) return;

  var slug = root.getAttribute("data-chat");
  var stream = document.querySelector("[data-chat-stream]");
  var form = document.querySelector("[data-chat-form]");
  var input = form ? form.querySelector("textarea") : null;
  var fileInput = form ? form.querySelector('input[type="file"]') : null;
  var attachBtn = form ? form.querySelector("[data-attach]") : null;
  var attachSummary = form ? form.querySelector("[data-attach-summary]") : null;
  var presenceEl = document.querySelector("[data-chat-presence]");
  var proto = location.protocol === "https:" ? "wss" : "ws";
  var online = 0;
  var ws;

  function appendMessage(d) {
    if (!stream || document.getElementById("post-" + d.id)) return; // dedupe
    var wrap = document.createElement("div");
    wrap.className = "flex gap-3";
    wrap.id = "post-" + d.id;
    wrap.innerHTML =
      '<div class="flex-1 min-w-0">' +
      '<p class="text-sm"><span class="font-medium text-base-content"></span>' +
      ' <time class="text-xs text-base-content/40 ml-1"></time></p>' +
      '<div class="prose prose-sm max-w-none text-base-content/90" data-body></div></div>';
    wrap.querySelector(".font-medium").textContent = d.author;
    var t = wrap.querySelector("time");
    t.textContent = "just now";
    t.dateTime = d.created;
    wrap.querySelector("[data-body]").innerHTML = d.body_html;
    stream.appendChild(wrap);
    wrap.scrollIntoView({ block: "nearest" });
  }

  function presence(d) {
    online = d.event === "join" ? online + 1 : Math.max(0, online - 1);
    if (presenceEl) presenceEl.textContent = online > 0 ? "● " + online + " online" : "";
  }

  function connect() {
    ws = new WebSocket(proto + "://" + location.host + "/ws/parletre/" + slug + "/");
    ws.onmessage = function (e) {
      var d;
      try { d = JSON.parse(e.data); } catch (_) { return; }
      if (d.kind === "message") appendMessage(d);
      else if (d.kind === "presence") presence(d);
    };
  }

  function autogrow() {
    if (!input) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 144) + "px";
  }

  // --- composer enhancements ---
  if (input) {
    input.setAttribute("rows", "1");
    autogrow();
    input.addEventListener("input", autogrow);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (input.value.trim() && typeof form.requestSubmit === "function") {
          form.requestSubmit();
        }
      }
    });
  }
  if (attachBtn && fileInput) {
    attachBtn.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      if (!attachSummary) return;
      var names = Array.prototype.map.call(fileInput.files, function (f) { return f.name; });
      attachSummary.textContent = names.length ? names.join(", ") : "";
    });
  }

  if (form && input) {
    form.addEventListener("submit", function (e) {
      if (!ws || ws.readyState !== 1) return; // fall back to a normal POST
      if (fileInput && fileInput.files && fileInput.files.length) return; // multipart POST
      var replyField = form.querySelector("[name=reply_to]");
      if (replyField && replyField.value) return; // replies POST so reply_to + context are saved/rendered
      var body = input.value.trim();
      if (!body) { e.preventDefault(); return; }
      e.preventDefault();
      ws.send(JSON.stringify({ body: body }));
      input.value = "";
      autogrow();
    });
  }

  connect();
})();
