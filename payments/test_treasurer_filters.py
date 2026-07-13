"""Tests for treasurer template filters (task #435 — provenance hover)."""

import pytest

from payments.templatetags.treasurer_filters import provenance_lines


@pytest.mark.parametrize(
    "notes, expected",
    [
        ("", []),
        ("   ", []),
        (
            "[tz-import:tuition-24-25#1] | installment: 1st | method unrecorded in ledger",
            [
                "Treasurer ledger ref · tuition-24-25#1",
                "installment: 1st",
                "method unrecorded in ledger",
            ],
        ),
        (
            "[tz-import:dues-25-26#17] | method unrecorded in ledger",
            [
                "Treasurer ledger ref · dues-25-26#17",
                "method unrecorded in ledger",
            ],
        ),
        (
            "[stripe-import:ch_3TZxFRKD60xePWRa1QgWKIsY]",
            ["Stripe charge · ch_3TZxFRKD60xePWRa1QgWKIsY"],
        ),
        (
            "[stripe-import:ch_3SwnMBKD60xePWRa1oKdtQxp] (provisional — confirm via dashboard)",
            [
                "Stripe charge · ch_3SwnMBKD60xePWRa1oKdtQxp (provisional — confirm via dashboard)",
            ],
        ),
        (
            "[assume-skip dues-24-25]",
            ["assume-skip dues-24-25"],
        ),
        (
            "Paid by check #4021",
            ["Paid by check #4021"],
        ),
    ],
)
def test_provenance_lines(notes, expected):
    assert provenance_lines(notes) == expected


from django.template.loader import render_to_string  # noqa: E402


def _render(**ctx):
    base = {"source": "staff", "source_label": "Entered by staff",
            "notes": "", "member_note": "", "trigger": "icon"}
    base.update(ctx)
    return render_to_string("payments/treasurer/_provenance_popover.html", base)


def test_popover_icon_shows_source_and_cleaned_notes():
    html = _render(
        source="imported", source_label="Imported from treasurer ledger",
        notes="[tz-import:tuition-24-25#1] | method unrecorded in ledger",
        trigger="icon",
    )
    assert "Imported from treasurer ledger" in html
    assert "Treasurer ledger ref · tuition-24-25#1" in html
    assert "method unrecorded in ledger" in html
    assert "data-prov-trigger" in html
    assert "data-prov-panel" in html


def test_popover_icon_empty_when_no_notes():
    html = _render(trigger="icon")
    assert html.strip() == ""


def test_popover_badge_always_shows_but_no_hover_without_notes():
    html = _render(source_label="Entered by staff", trigger="badge")
    assert "Entered by staff" in html
    assert "data-prov-trigger" not in html


def test_popover_badge_gets_hover_with_notes():
    html = _render(
        source="imported", source_label="Imported from treasurer ledger",
        notes="[tz-import:dues-25-26#17] | method unrecorded in ledger",
        trigger="badge",
    )
    assert "Imported from treasurer ledger" in html
    assert "data-prov-trigger" in html
    assert "Treasurer ledger ref · dues-25-26#17" in html


def test_popover_shows_member_note():
    html = _render(notes="", member_note="Paid at the door, will confirm.", trigger="icon")
    assert "Paid at the door, will confirm." in html
    assert "data-prov-trigger" in html
