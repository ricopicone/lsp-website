"""Upload content types (found while doing task #506).

**Read the docstring on the first test before trusting these.** The failure they
guard against is container-only, so they are weak where they run.
"""

from __future__ import annotations

import mimetypes


def test_webp_is_typed_as_an_image():
    """WebP must type as image/webp so a direct link displays rather than
    downloads — the no-JS path of both lightboxes.

    Honest caveat: this assertion passes vacuously on macOS and on the CI
    runner, which both ship a system mime table that already knows .webp. The
    real gap is the container, where mimetypes.knownfiles is empty and Python
    3.10's built-in table has no .webp, so only config.settings.base's
    add_type() supplies it. The authoritative check is to run
    mimetypes.guess_type('x.webp') inside the deployed container; this test
    exists so that deleting that add_type() line is at least a deliberate act.
    """
    assert mimetypes.guess_type("logo.webp")[0] == "image/webp"


def test_docx_is_typed_as_a_word_document():
    """One .docx sits in the private bucket; the built-in table has no entry
    for it in any Python version, so this one is not merely a 3.10 gap."""
    assert mimetypes.guess_type("minutes.docx")[0] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
