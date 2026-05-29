"""Rotating Lacanian aphorisms surfaced in the site footer.

One is picked per page render via ``core.context_processors.aphorism``.
Keep the list short and well-attested — these will rotate hundreds of
times for any member visiting often, so quality beats quantity. Add or
revise as suits the Web Coordinator's editorial taste; the page need
not show one at all if the list is empty.
"""

from __future__ import annotations

APHORISMS: list[dict[str, str]] = [
    {"quote": "What constitutes me as a subject is my question.",
     "source": "Écrits"},
    {"quote": "The unconscious is structured like a language.",
     "source": "Seminar XI"},
    {"quote": "There is no sexual relation.",
     "source": "Seminar XX, Encore"},
    {"quote": "Love is giving what one does not have to someone who does not want it.",
     "source": "Seminar VIII"},
    {"quote": "The Real is the impossible.",
     "source": "Seminar XI"},
    {"quote": "I think where I am not; I am where I do not think.",
     "source": "Écrits"},
    {"quote": "Don't give ground on your desire.",
     "source": "Seminar VII"},
    {"quote": "A letter always arrives at its destination.",
     "source": "Seminar on 'The Purloined Letter'"},
    {"quote": "A signifier is what represents the subject for another signifier.",
     "source": "Écrits"},
    {"quote": "Anxiety is what does not deceive.",
     "source": "Seminar X"},
    {"quote": "Man's desire is the desire of the Other.",
     "source": "Écrits"},
    {"quote": "The Other does not exist.",
     "source": "Seminar XX"},
    {"quote": "Where it was, there I shall come to be.",
     "source": "Écrits"},
    {"quote": "The truth has the structure of a fiction.",
     "source": "Seminar VII"},
    {"quote": "The unconscious is the discourse of the Other.",
     "source": "Écrits"},
    {"quote": "The function of speech is not to inform but to evoke.",
     "source": "Écrits"},
    {"quote": "What does not come to light in the symbolic appears in the real.",
     "source": "Seminar III"},
    {"quote": "Desire is the metonymy of the lack of being.",
     "source": "Écrits"},
    {"quote": "An analyst is authorized only by himself.",
     "source": "Proposition of 9 October 1967"},
    {"quote": "The non-dupes err.",
     "source": "Seminar XXI"},
    {"quote": "The phallus can only play its role veiled.",
     "source": "Écrits"},
    {"quote": "There is something of the One.",
     "source": "Seminar XX"},
]
