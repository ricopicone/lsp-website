/*
 * The event edit page (task #817).
 *
 * 1. Unsaved changes. The details form's Save sits in a bar that sticks to the
 *    bottom of the screen. Once anything in the form differs from how the page
 *    loaded, the bar says so, and leaving the page (including by pressing a
 *    button in one of the separately-saved forms below) asks first. The form's
 *    own Save never asks.
 *
 * 2. Adding a CE organization. The add form lives in a <dialog> and is posted
 *    by fetch, asking for JSON, so the details form keeps whatever has not
 *    been saved yet. The view applies the new organization to the event at
 *    once, so it is ticked in the list and counted as saved, not as a change.
 *    Without JavaScript the dialog never opens; a refused add rendered by the
 *    server arrives with the dialog open, and is reopened as a modal here.
 *
 * Only the `hidden` attribute is toggled from here, never a class: Tailwind
 * scans templates only, so a class set from JavaScript would be missing from
 * the production build (see submit-guard.js).
 */
(function () {
  "use strict";

  var form = document.getElementById("event-details-form");
  if (!form) return;

  // ---- 1. Unsaved changes ------------------------------------------------

  function snapshot() {
    var data = {};
    new FormData(form).forEach(function (value, name) {
      if (name === "csrfmiddlewaretoken") return;
      (data[name] = data[name] || []).push(String(value).replace(/\r\n/g, "\n"));
    });
    Object.keys(data).forEach(function (name) { data[name].sort(); });
    return data;
  }

  function same(a, b) {
    var keys = Object.keys(a).concat(Object.keys(b));
    for (var i = 0; i < keys.length; i++) {
      var x = a[keys[i]] || [], y = b[keys[i]] || [];
      if (x.length !== y.length) return false;
      for (var j = 0; j < x.length; j++) if (x[j] !== y[j]) return false;
    }
    return true;
  }

  var baseline = snapshot();
  var saving = false;
  var note = form.querySelector("[data-dirty-note]");
  // Rendered back from a POST (a refused save, or "Keep editing" in the
  // review dialog): what the page loaded with is not what is saved.
  var unsaved = form.hasAttribute("data-unsaved");

  function dirty() { return unsaved || !same(baseline, snapshot()); }

  function refresh() { if (note) note.hidden = !dirty(); }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  form.addEventListener("submit", function () { saving = true; });
  refresh();

  window.addEventListener("beforeunload", function (e) {
    if (saving || !dirty()) return;
    e.preventDefault();
    e.returnValue = "";
  });
  // A page restored from the back/forward cache is live again.
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) { saving = false; refresh(); }
  });

  // ---- 2. The CE organization dialog ---------------------------------------

  var dialog = document.getElementById("ce-org-dialog");
  if (!dialog) return;
  var addForm = dialog.querySelector("[data-ce-org-form]");
  var list = document.getElementById("ce-org-list");
  var added = document.querySelector("[data-ce-added]");

  function showErrors(errors) {
    var slots = addForm.querySelectorAll("[data-error-for]");
    for (var i = 0; i < slots.length; i++) {
      var messages = (errors || {})[slots[i].getAttribute("data-error-for")];
      slots[i].textContent = messages ? [].concat(messages).join(", ") : "";
      slots[i].hidden = !messages;
    }
  }

  function resetAddForm() {
    addForm.reset();
    showErrors(null);
    // Back to a single logo input.
    var rows = addForm.querySelectorAll("[data-logo-row]");
    for (var i = 1; i < rows.length; i++) rows[i].remove();
    var more = addForm.querySelector("[data-add-logo]");
    if (more) more.removeAttribute("hidden");
  }

  function open() {
    if (added) added.hidden = true;
    dialog.showModal();
    var first = addForm.querySelector("input[name='name']");
    if (first) first.focus();
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-open-dialog='ce-org-dialog']")) { open(); return; }
    if (e.target.closest("[data-close-dialog]")) dialog.close();
  });

  // A refused add without JavaScript comes back with the dialog open inline.
  if (dialog.hasAttribute("open")) { dialog.close(); dialog.showModal(); }

  function addRow(org) {
    var empty = list.querySelector("[data-ce-empty]");
    if (empty) empty.remove();

    var row = document.createElement("div");
    row.className = "flex items-center gap-3";
    var label = document.createElement("label");
    label.className = "flex flex-1 cursor-pointer items-center gap-3";
    var box = document.createElement("input");
    box.type = "checkbox";
    box.name = "ce_organizations";
    box.value = String(org.pk);
    box.className = "checkbox checkbox-sm";
    box.checked = true;
    label.appendChild(box);
    org.logos.forEach(function (url) {
      var frame = document.createElement("span");
      frame.className = "inline-flex items-center rounded border border-base-300/60 bg-white p-1.5";
      var img = document.createElement("img");
      img.src = url;
      img.alt = org.name + " logo";
      img.className = "max-h-8 max-w-28 object-contain";
      frame.appendChild(img);
      label.appendChild(frame);
    });
    var name = document.createElement("span");
    name.className = "text-sm text-base-content";
    name.textContent = org.name;
    label.appendChild(name);
    row.appendChild(label);
    var manage = document.createElement("a");
    manage.href = org.manage_url;
    manage.className = "link link-hover text-xs text-base-content/50";
    manage.textContent = "Manage logos";
    row.appendChild(manage);
    list.appendChild(row);

    // Already applied on the server, so it is part of the saved state.
    (baseline.ce_organizations = baseline.ce_organizations || []).push(String(org.pk));
    baseline.ce_organizations.sort();
    refresh();
  }

  var busy = false;
  addForm.addEventListener("submit", function (e) {
    // Prevented here, on the form, so submit-guard.js (on document, bubble
    // phase) sees defaultPrevented and leaves this form alone.
    e.preventDefault();
    if (busy) return;
    busy = true;
    var button = addForm.querySelector("button[type='submit']");
    if (button) button.classList.add("is-submitting");

    fetch(addForm.action, {
      method: "POST",
      body: new FormData(addForm),
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(
          function (data) { return { ok: response.ok, data: data }; },
          function () { return { ok: false, data: {} }; }
        );
      })
      .then(function (result) {
        if (result.ok) {
          addRow(result.data);
          resetAddForm();
          dialog.close();
          if (added) {
            added.textContent = "Added " + result.data.name +
              ". It's ticked and already applied to this event.";
            added.hidden = false;
          }
        } else {
          showErrors(result.data.errors || {
            __all__: ["The organization couldn't be added. Please try again."],
          });
        }
      })
      .catch(function () {
        showErrors({ __all__: ["The organization couldn't be added. Please try again."] });
      })
      .then(function () {
        busy = false;
        if (button) button.classList.remove("is-submitting");
      });
  });
})();
