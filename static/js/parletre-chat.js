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
  var replyField = form ? form.querySelector("[name=reply_to]") : null;
  var replyBanner = form ? form.querySelector("[data-reply-banner]") : null;
  var replyName = replyBanner ? replyBanner.querySelector("[data-reply-name]") : null;
  var proto = location.protocol === "https:" ? "wss" : "ws";
  var ws;
  var pingTimer;

  function setReply(id, author) {
    if (!replyField) return;
    replyField.value = id;
    if (replyBanner) replyBanner.hidden = false;
    if (replyName) replyName.textContent = author || "";
    if (input) input.focus();
  }
  function clearReply() {
    if (replyField) replyField.value = "";
    if (replyBanner) replyBanner.hidden = true;
  }
  // Client-side reply: intercept Reply links (server-rendered + live-appended)
  // and the cancel button — set the composer instead of reloading.
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-reply-to]");
    if (link) {
      e.preventDefault();
      setReply(link.getAttribute("data-reply-to"), link.getAttribute("data-reply-author"));
      return;
    }
    if (e.target.closest("[data-reply-cancel]")) {
      e.preventDefault();
      clearReply();
    }
  });

  function replyHref(id) {
    // Preserve the current query (e.g. ?tab=chat when embedded) + add reply_to.
    var params = new URLSearchParams(location.search);
    params.set("reply_to", id);
    return location.pathname + "?" + params.toString() + "#composer";
  }

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
    // "In reply to …" context line above the body.
    if (d.reply_to) {
      var rc = document.createElement("a");
      rc.className =
        "flex items-center gap-1 text-xs text-base-content/50 border-l-2 " +
        "border-base-300 pl-2 mb-1 hover:text-primary truncate";
      rc.href = "#post-" + d.reply_to.id;
      rc.textContent = "↩ " + d.reply_to.author + ": " + d.reply_to.excerpt;
      var flex = wrap.querySelector(".flex-1");
      flex.insertBefore(rc, flex.querySelector("[data-body]"));
    }
    // Give live messages a Reply control immediately (no refresh needed);
    // edit/delete/react render server-side on the next load.
    if (form) {
      var actions = document.createElement("div");
      actions.className = "flex items-center gap-3 mt-1 text-xs text-base-content/40";
      var reply = document.createElement("a");
      reply.className = "hover:text-primary";
      reply.textContent = "Reply";
      reply.href = replyHref(d.id);
      reply.setAttribute("data-reply-to", d.id);
      reply.setAttribute("data-reply-author", d.author);
      actions.appendChild(reply);
      wrap.querySelector(".flex-1").appendChild(actions);
    }
    stream.appendChild(wrap);
    wrap.scrollIntoView({ block: "nearest" });
  }

  function presence(d) {
    if (!presenceEl) return;
    var roster = d.roster || [];
    presenceEl.textContent = roster.length ? "● " + roster.join(", ") : "";
  }

  function connect() {
    ws = new WebSocket(proto + "://" + location.host + "/ws/parletre/" + slug + "/");
    ws.onmessage = function (e) {
      var d;
      try { d = JSON.parse(e.data); } catch (_) { return; }
      if (d.kind === "message") appendMessage(d);
      else if (d.kind === "presence") presence(d);
    };
    // Keep-alive: refresh presence so the "who's here" list survives idle time.
    ws.onopen = function () {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = setInterval(function () {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify({ ping: true }));
      }, 25000);
    };
    ws.onclose = function () { if (pingTimer) clearInterval(pingTimer); };
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
      var body = input.value.trim();
      if (!body) { e.preventDefault(); return; }
      e.preventDefault();
      var msg = { body: body };
      if (replyField && replyField.value) msg.reply_to = replyField.value;  // realtime reply
      ws.send(JSON.stringify(msg));
      input.value = "";
      clearReply();
      autogrow();
    });
  }

  connect();
})();
