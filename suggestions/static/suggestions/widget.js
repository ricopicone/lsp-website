// Floating "Suggest a change" widget.
//
// Opens a modal pre-filled with the current page, then posts the suggestion via
// fetch so the member never leaves the page. Degrades to a normal form POST if
// anything here fails (the form's action/method are real).
(function () {
  "use strict";

  var modal = document.getElementById("lsp-suggest-modal");
  var openBtn = document.querySelector("[data-suggest-open]");
  if (!modal || !openBtn || typeof modal.showModal !== "function") return;

  var form = modal.querySelector("[data-suggest-form]");
  var pageUrl = modal.querySelector("[data-suggest-page-url]");
  var pageTitle = modal.querySelector("[data-suggest-page-title]");
  var contextField = modal.querySelector("[data-suggest-context]");
  var pageLabel = modal.querySelector("[data-suggest-page-label]");
  var errorBox = modal.querySelector("[data-suggest-error]");
  var submitBtn = modal.querySelector("[data-suggest-submit]");

  function captureContext() {
    if (pageUrl) pageUrl.value = window.location.pathname;
    if (pageTitle) pageTitle.value = document.title;
    if (contextField) {
      contextField.value = JSON.stringify({
        href: window.location.href,
        referrer: document.referrer || "",
        viewport: window.innerWidth + "x" + window.innerHeight,
        user_agent: navigator.userAgent,
      });
    }
    if (pageLabel) {
      pageLabel.textContent = "About this page: " + window.location.pathname;
    }
  }

  function showToast(message) {
    var wrap = document.createElement("div");
    wrap.className = "toast toast-end z-50";
    wrap.innerHTML =
      '<div class="alert alert-success"><span></span></div>';
    wrap.querySelector("span").textContent = message;
    document.body.appendChild(wrap);
    setTimeout(function () { wrap.remove(); }, 4000);
  }

  openBtn.addEventListener("click", function () {
    captureContext();
    if (errorBox) errorBox.classList.add("hidden");
    modal.showModal();
  });

  var cancelBtn = modal.querySelector("[data-suggest-cancel]");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () { modal.close(); });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      if (submitBtn) submitBtn.disabled = true;

      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (submitBtn) submitBtn.disabled = false;
          if (result.ok && result.data.ok) {
            modal.close();
            form.reset();
            showToast("Thanks — your suggestion was sent.");
          } else {
            var msg = "Sorry, that didn't go through. Please check the form.";
            var errs = result.data && result.data.errors;
            if (errs) {
              var firstKey = Object.keys(errs)[0];
              if (firstKey && errs[firstKey][0]) msg = errs[firstKey][0];
            }
            if (errorBox) {
              errorBox.textContent = msg;
              errorBox.classList.remove("hidden");
            }
          }
        })
        .catch(function () {
          // Network/JS failure — fall back to a plain navigation POST.
          // form.submit() does not re-fire this submit handler.
          if (submitBtn) submitBtn.disabled = false;
          form.submit();
        });
    });
  }
})();
