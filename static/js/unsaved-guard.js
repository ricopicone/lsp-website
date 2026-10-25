/*
 * Pages with several independently saved forms lose what was typed in one
 * when a button in another is pressed (task #820, the #817 lesson). A form
 * marked `data-warn-unsaved` that differs from how the page loaded makes
 * leaving the page ask first; submitting that form itself never asks.
 * The event edit page has its own fuller version (event-edit.js).
 */
(function () {
  "use strict";
  var forms = [].slice.call(document.querySelectorAll("form[data-warn-unsaved]"));
  if (!forms.length) return;

  function snapshot(form) {
    var out = [];
    new FormData(form).forEach(function (value, name) {
      if (name !== "csrfmiddlewaretoken") out.push(name + "=" + String(value).replace(/\r\n/g, "\n"));
    });
    return out.join("&");
  }

  var saved = forms.map(snapshot);
  var submitting = null;
  forms.forEach(function (form) {
    form.addEventListener("submit", function () { submitting = form; });
  });

  window.addEventListener("beforeunload", function (e) {
    var dirty = forms.some(function (form, i) {
      return form !== submitting && snapshot(form) !== saved[i];
    });
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = "";
  });
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) submitting = null;
  });
})();
