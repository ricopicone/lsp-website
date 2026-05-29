"""Vetted Lacanian aphorisms surfaced in the site footer.

One is picked per page render via ``core.context_processors.aphorism``.

Each entry has:

- ``quote`` — the visible aphorism
- ``short_attribution`` — what's shown next to the quote (small chip)
- ``full_attribution`` — the bibliographic detail; surfaces as a hover
  tooltip (HTML ``title`` attribute) in the footer

Source: ``../lacan_aphorisms.json`` in the parent ``LSP-Web-Coordinator``
folder — kept in sync by the Web Coordinator. Inlined here so the runtime
doesn't depend on a sibling-directory file.
"""

from __future__ import annotations

APHORISMS: list[dict[str, str]] = [
    {
        "quote": "The unconscious is structured like a language.",
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts of Psychoanalysis, Bk XI (Sheridan; "
            "first English Hogarth 1977, Norton 1978); Fr. 1964. Qualified in "
            "Encore, Bk XX (Fink, Norton 1998; Fr. 1972–73)."
        ),
    },
    {
        "quote": "The unconscious is the discourse of the Other.",
        "short_attribution": "Écrits (“Purloined Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “Seminar on ‘The Purloined Letter’”; "
            "Fr. 1956."
        ),
    },
    {
        "quote": "Desire is the desire of the Other.",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960. Also Bk XI (1964)."
        ),
    },
    {
        "quote": "Desire is always desire for something else.",
        "short_attribution": "Écrits (“Instance of the Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Instance of the Letter…”; "
            "Fr. 1957."
        ),
    },
    {
        "quote": "The symptom is a metaphor.",
        "short_attribution": "Écrits (“Instance of the Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Instance of the Letter…”; "
            "Fr. 1957."
        ),
    },
    {
        "quote": "Desire is a metonymy.",
        "short_attribution": "Écrits (“Instance of the Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Instance of the Letter…”; "
            "Fr. 1957. Fuller “metonymy of the want-to-be” in "
            "“The Direction of the Treatment”; Fr. 1958."
        ),
    },
    {
        "quote": "The signified slides incessantly beneath the signifier.",
        "short_attribution": "Écrits (“Instance of the Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Instance of the Letter…”; "
            "Fr. 1957."
        ),
    },
    {
        "quote": "A signifier is what represents the subject for another signifier.",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960. Also Bk XI (1964)."
        ),
    },
    {
        "quote": "I think where I am not, therefore I am where I do not think.",
        "short_attribution": "Écrits (“Instance of the Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Instance of the Letter…”; "
            "Fr. 1957."
        ),
    },
    {
        "quote": "There is no sexual relationship.",
        "short_attribution": "Seminar XX",
        "full_attribution": (
            "Encore, Bk XX (Fink, Norton 1998); Fr. 1972–73. Developed from "
            "Bk XVII (Grigg, Norton 2007; Fr. 1969–70)."
        ),
    },
    {
        "quote": "There is no such thing as Woman.",
        "short_attribution": "Seminar XX",
        "full_attribution": "Encore, Bk XX (Fink, Norton 1998); Fr. 1972–73.",
    },
    {
        "quote": "For a man, a woman is a symptom.",
        "short_attribution": "Seminar XXII (R.S.I.)",
        "full_attribution": (
            "R.S.I., Bk XXII (no authorized English edition); Fr. 1974–75, "
            "lesson of 21 Jan 1975. Lacan adds that it is reciprocal."
        ),
    },
    {
        "quote": "What makes up for the absence of the sexual relationship is love.",
        "short_attribution": "Seminar XX",
        "full_attribution": "Encore, Bk XX (Fink, Norton 1998); Fr. 1972–73.",
    },
    {
        "quote": "To love is to give what you do not have.",
        "short_attribution": "Seminar VIII",
        "full_attribution": (
            "Transference, Bk VIII (Fink, Polity 2015); Fr. 1960–61. Variant "
            "“…to someone who does not want it” in Bk XII (no authorized "
            "English edition; Fr. 1964–65)."
        ),
    },
    {
        "quote": "Anxiety is not without an object.",
        "short_attribution": "Seminar X",
        "full_attribution": "Anxiety, Bk X (Price, Polity 2014); Fr. 1962–63.",
    },
    {
        "quote": "The real is that which always returns to the same place.",
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts…, Bk XI (Sheridan, Norton 1978); "
            "Fr. 1964."
        ),
    },
    {
        "quote": "The real is the impossible.",
        "short_attribution": "Seminar XVII",
        "full_attribution": (
            "The Other Side of Psychoanalysis, Bk XVII (Grigg, Norton 2007); "
            "Fr. 1969–70. Antecedent in Bk XII (Fr. 1964–65); restated in the "
            "1975 MIT lecture (Scilicet 6/7)."
        ),
    },
    {
        "quote": "Truth has the structure of a fiction.",
        "short_attribution": "Écrits (“The Freudian Thing”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Freudian Thing” (p. 340); "
            "Fr. 1955. Cf. Ethics, Bk VII (Porter, Norton 1992; Fr. 1959–60)."
        ),
    },
    {
        "quote": "There is no Other of the Other.",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960."
        ),
    },
    {
        "quote": "There is no metalanguage.",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960."
        ),
    },
    {
        "quote": "A letter always arrives at its destination.",
        "short_attribution": "Écrits (“Purloined Letter”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “Seminar on ‘The Purloined Letter’”; "
            "Fr. 1956."
        ),
    },
    {
        "quote": (
            "I always speak the truth — not the whole truth, because saying it "
            "all is impossible."
        ),
        "short_attribution": "Television",
        "full_attribution": (
            "Television, ed. Copjec (Hollier, Krauss & Michelson, Norton 1990); "
            "Fr. 1974."
        ),
    },
    {
        "quote": "Jouissance is forbidden to whoever speaks as such.",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960."
        ),
    },
    {
        "quote": "God is unconscious.",
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts…, Bk XI (Sheridan, Norton 1978); "
            "Fr. 1964."
        ),
    },
    {
        "quote": "Che vuoi? — What do you want?",
        "short_attribution": "Écrits (“Subversion”)",
        "full_attribution": (
            "Écrits (Fink, Norton 2006), “The Subversion of the Subject…”; "
            "Fr. 1960 (from Cazotte’s Le Diable amoureux)."
        ),
    },
    {
        "quote": "What is foreclosed from the symbolic reappears in the real.",
        "short_attribution": "Seminar III / Écrits",
        "full_attribution": (
            "The Psychoses, Bk III (Grigg, Norton 1993; Fr. 1955–56); and "
            "Écrits (Fink, Norton 2006), “On a Question Prior to Any Possible "
            "Treatment of Psychosis”; Fr. 1957–58. Doctrinal condensation, "
            "not one verbatim line."
        ),
    },
    {
        "quote": "The non-duped err.",
        "short_attribution": "Seminar XXI",
        "full_attribution": (
            "Les non-dupes errent, Bk XXI (no authorized English edition); "
            "Fr. 1973–74. Homophone of les Noms-du-Père."
        ),
    },
    {
        "quote": "I am not a poet, but a poem.",
        "short_attribution": "Television",
        "full_attribution": (
            "Television, ed. Copjec (Hollier, Krauss & Michelson, Norton 1990); "
            "Fr. 1974."
        ),
    },
    {
        "quote": "I am looked at, that is to say, I am a picture.",
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts…, Bk XI (Sheridan, Norton 1978); "
            "Fr. 1964."
        ),
    },
    {
        "quote": "The picture is in my eye, but I am in the picture.",
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts…, Bk XI (Sheridan, Norton 1978); "
            "Fr. 1964."
        ),
    },
    {
        "quote": (
            "The mirror stage is a drama whose internal thrust is precipitated "
            "from insufficiency to anticipation."
        ),
        "short_attribution": "Écrits (“Mirror Stage”)",
        "full_attribution": (
            "Quoted wording from Sheridan, Écrits: A Selection (Norton); "
            "also in Écrits (Fink, Norton 2006, phrased differently); Fr. 1949."
        ),
    },
    {
        "quote": (
            "What is realized in my history is … the future anterior of what "
            "I shall have been for what I am in the process of becoming."
        ),
        "short_attribution": "Écrits (“Function and Field”)",
        "full_attribution": (
            "Quoted wording from Sheridan, Écrits: A Selection (Norton); "
            "also in Écrits (Fink, Norton 2006, phrased differently); "
            "Fr. 1953 (Rome Discourse)."
        ),
    },
    {
        "quote": (
            "I love you, but, because inexplicably I love in you something "
            "more than you — the objet a — I mutilate you."
        ),
        "short_attribution": "Seminar XI",
        "full_attribution": (
            "The Four Fundamental Concepts…, Bk XI (Sheridan, Norton 1978); "
            "Fr. 1964."
        ),
    },
]
