"""Submit a rendered form the way a browser would (task #820).

Tests that POST a hand-built dict at a view skip what the browser actually
sends: the hidden fields the page rendered, CRLF line endings from a
<textarea>, unchecked checkboxes left out, every value of a multi-select.
Parse the page and post what it holds instead
(events/test_confirm_dialog_roundtrip.py is where this started, task #817).

Not a test module (no ``test_`` prefix), so pytest does not collect it.
"""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser


class FormParser(HTMLParser):
    """Collect each <form>'s successful controls the way a browser submits them."""

    def __init__(self):
        super().__init__()
        self.forms, self.attrs, self._form, self._textarea, self._select = [], [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = []
            self.forms.append(self._form)
            self.attrs.append(a)
        if self._form is None:
            return
        name = a.get("name")
        if tag == "input" and name:
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self._form.append((name, a.get("value", "on")))
            elif kind not in ("submit", "button", "file"):
                self._form.append((name, a.get("value", "")))
        elif tag == "textarea":
            self._textarea = [name, ""]
        elif tag == "select":
            self._select = [name, None, None]
        elif tag == "option" and self._select:
            if self._select[2] is None:
                self._select[2] = a.get("value", "")
            if "selected" in a:
                self._select[1] = a.get("value", "")

    def handle_data(self, data):
        if self._textarea:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "textarea" and self._textarea:
            name, value = self._textarea
            # A browser drops one newline straight after <textarea>, and
            # submits the content's line breaks as CRLF.
            if value.startswith("\n"):
                value = value[1:]
            value = unescape(value).replace("\r\n", "\n").replace("\n", "\r\n")
            if name:
                self._form.append((name, value))
            self._textarea = None
        elif tag == "select" and self._select:
            name, chosen, first = self._select
            self._form.append((name, chosen if chosen is not None else first))
            self._select = None
        elif tag == "form":
            self._form = None


def browser_form(html, *, action=None, field=None):
    """The fields a browser would submit from one form on the page.

    Pick the form by ``action`` (a substring of its action attribute) or by a
    ``field`` name it contains. Returns ``{name: [values]}`` without the CSRF
    token, ready for ``client.post``.
    """
    parser = FormParser()
    parser.feed(html)
    for attrs, controls in zip(parser.attrs, parser.forms):
        if action is not None and action not in (attrs.get("action") or ""):
            continue
        if field is not None and not any(k == field for k, _ in controls):
            continue
        data = {}
        for key, value in controls:
            data.setdefault(key, []).append(unescape(value))
        data.pop("csrfmiddlewaretoken", None)
        return data
    raise AssertionError(f"no form with action={action!r} field={field!r}")
