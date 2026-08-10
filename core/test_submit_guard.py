"""Pin the site-wide submit-once guard's three silent-failure paths (task #545).

The guard itself is browser behaviour and can't be unit-tested here, but each
of the ways it can quietly stop working is a file check:

* dropping the ``<script>`` from ``base.html`` disables it everywhere at once,
  with nothing on any page to show it;
* writing its classes as Tailwind utilities strips them from the **production**
  build only (the v4 build scans ``**/templates/**/*.html``, and these classes
  are emitted from JavaScript) — dev and CI look fine;
* reaching for the ``disabled`` attribute drops a named submit button's
  ``name``/``value`` from the POST, turning approve/decline pairs into silent
  no-ops.

Reads files only (no DB).
"""
from pathlib import Path

from django.conf import settings

BASE = Path(settings.BASE_DIR)
SCRIPT = BASE / "static" / "js" / "submit-guard.js"
BASE_TEMPLATE = BASE / "core" / "templates" / "core" / "base.html"
INPUT_CSS = BASE / "assets" / "css" / "input.css"


def test_base_template_loads_the_submit_guard():
    assert SCRIPT.exists(), f"{SCRIPT} is missing"
    assert "js/submit-guard.js" in BASE_TEMPLATE.read_text(encoding="utf-8"), (
        "core/base.html must load static/js/submit-guard.js — it is the only "
        "thing stopping a slow POST from being sent twice, and it is loaded "
        "in exactly one place."
    )


def test_guard_classes_are_hand_written_css():
    """Tailwind only scans templates, so JS-emitted classes must be real CSS.

    Written as a Tailwind utility instead, these would be stripped from the
    production build and the button would lock without ever looking locked —
    a failure that never reproduces locally. Same reason ``.hp-wrap`` is
    hand-written.
    """
    css = INPUT_CSS.read_text(encoding="utf-8")
    for selector in (".is-submitting", ".lsp-spinner"):
        assert selector in css, (
            f"{selector} is emitted by static/js/submit-guard.js, so it must "
            f"be declared in assets/css/input.css — Tailwind v4 scans "
            f"templates only and would drop it from the prod build."
        )


def test_guard_never_touches_the_disabled_attribute():
    """A disabled submitter is left out of the POST.

    The HTML form-submission algorithm fires ``submit`` *before* it builds the
    entry list, so disabling the pressed button inside a submit handler drops
    its ``name``/``value``. Twenty-eight buttons on this site carry a ``name``
    (the treasurer's Reconcile approve/decline pair, the plan queue,
    advancement and cartel decisions), and every one of them would post as an
    action-less request. The guard greys buttons with a class and blocks
    re-submits with a flag instead.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith(("//", "*", "/*"))
    )
    # `aria-disabled` is the right thing to set and is inert to serialization —
    # it tells assistive tech what pointer-events and the flag already enforce.
    code = code.replace("aria-disabled", "")
    assert "disabled" not in code, (
        "static/js/submit-guard.js must not set or read the `disabled` "
        "attribute: disabling a submit button during submit removes its "
        "name/value from the POST. Grey it with the .is-submitting class and "
        "swallow the second submit with preventDefault instead."
    )
