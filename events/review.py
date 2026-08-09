"""Faculty editing review loop (task #295).

An *approved* event (one that is published and was minted from an approved
Programming-Committee proposal) carries an expectation that substantial content
changes pass back through the committee. Faculty may still make small edits —
fixing a typo, clarifying a sentence — without ceremony, but a wholesale rewrite
of the title or description should be reviewed.

We do **not** automate that judgement away (architecture §4.1, "space for the
singular"): when a faculty member edits a reviewable field we present a dialog
and let them certify the change as minor (adopted immediately) or submit it to
the committee queue. The ~20% description-change heuristic here only *advises*
that dialog — it never forces the choice.
"""

from __future__ import annotations

from difflib import SequenceMatcher

#: Content fields whose change triggers the certify-or-submit dialog. Other
#: edit-form fields (schedule_note, contact, record_video) are administrative
#: and always apply immediately.
REVIEWABLE_FIELDS = ("title", "description", "readings", "fee_note", "price")

#: Human labels for the reviewable fields, used in the dialog + review queue.
FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "readings": "Readings",
    "fee_note": "Fee note",
    "price": "Price",
}

#: Above this fraction of the description changed, the dialog *recommends* the
#: review path. Purely advisory — faculty still decide.
SUBSTANTIAL_THRESHOLD = 0.20


def change_ratio(old: str, new: str) -> float:
    """Fraction of text that changed between ``old`` and ``new`` (0.0–1.0).

    Built on :class:`difflib.SequenceMatcher` similarity; an unchanged field is
    0.0, a complete rewrite approaches 1.0. Used only as an advisory signal in
    the review dialog.
    """
    old = old or ""
    new = new or ""
    if not old and not new:
        return 0.0
    return 1.0 - SequenceMatcher(None, old, new).ratio()


# NOTE: a ``changed_reviewable_fields(event, cleaned_data)`` lived here and was
# never called. It read ``getattr(event, f)`` at call time, but ``event_edit``
# must snapshot the originals *before* binding — a ModelForm mutates the
# instance in place — so it would have returned wrong answers for the one view
# that could have used it. A dead helper that silently disagrees with the live
# code is what produced task #532's bug in the first place (see
# ``Program.public_program_year_q``), so it is gone rather than updated.
