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
