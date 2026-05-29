"""Seed the 2025-2026 academic year program from the Wix /seminars2025-2026 page.

One-shot management command (M12). Re-runnable; idempotent on (slug).
"""
# ruff: noqa: E501

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from events.models import Event

# (first, last) for faculty names — matched against existing User accounts.
SEMINARS = [
    {
        "title": "Psychoanalytic Training in the School of Lacan - Part 7",
        "slug":  "psychoanalytic-training-2025-26-part-7",
        "faculty": [("Marcelo", "Estrada")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 6, 30),
        "description": (
            "Dates and times: 5:30–8:00pm Pacific Time, last two Thursdays "
            "each month, September 2025 to June 2026; no classes in "
            "December 2025.\n\n"
            "Fee: $500 or School Tuition.\n\n"
            "Contact: Marcelo Estrada, marcelo.estrada@gmail.com."
        ),
    },
    {
        "title": "Four Lessons of Psychoanalysis",
        "slug":  "four-lessons-of-psychoanalysis-2025-26",
        "faculty": [("Robert", "Beshara")],
        "start_date": date(2025, 9, 4),
        "end_date":   date(2025, 9, 25),
        "description": (
            "Dates and times: 09/04, 09/11, 09/18, 09/25; 5–7pm Pacific Time.\n\n"
            "Fee: Donation to the School encouraged.\n\n"
            "Contact: besharaster@gmail.com."
        ),
    },
    {
        "title": "Reading Lacan's Seminar Book VIII: Transference",
        "slug":  "reading-seminar-viii-2025-26",
        "faculty": [("Yang", "Yu"), ("Cissy", "Hong Zhou")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: 8:30–11:00am, second and fourth Wednesdays each "
            "month, September to May (Beijing time, break in December and "
            "February).\n\n"
            "Fee: US $400 or School Tuition.\n\n"
            "Contact: celavieglove@126.com; cissyhongzhou@126.com."
        ),
    },
    {
        "title": (
            "Lacan Seminars XXIII and XXIV (1975–'77): On love, unknown knowing "
            "and the failure that takes flight"
        ),
        "slug":  "lacan-seminars-xxiii-xxiv-2025-26",
        "faculty": [("Benjamin", "Davidson")],
        "start_date": date(2026, 1, 7),
        "end_date":   date(2026, 6, 30),
        "description": (
            "Dates and times: online, biweekly Wednesdays 5–7pm Pacific Time, "
            "beginning 7 January 2026.\n\n"
            "Fee: Free of charge (voluntary donation to LSP encouraged).\n\n"
            "Contact: benjamdavidson@me.com."
        ),
    },
    {
        "title": "Intersubjectivity, Otherness and the (Irreducible) Position of analyst",
        "slug":  "intersubjectivity-otherness-position-2025-26",
        "faculty": [("Ruonan", "Liu")],
        "start_date": date(2025, 9, 1),
        "end_date":   date(2026, 4, 30),
        "description": (
            "Dates and times: 8:30–11:00am, the fourth Saturday of every "
            "month (Beijing Time), September to April; no sessions in February.\n\n"
            "Fee: 2000 Yuan (RMB) / US $300 or School Tuition.\n\n"
            "Contact: immanuelliu006@gmail.com."
        ),
    },
    {
        "title": "Secretaries to the Psychotic Subject – Seminar III",
        "slug":  "secretaries-psychotic-subject-2025-26",
        "faculty": [("Casey", "Butcher")],
        "start_date": date(2026, 1, 6),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: 1st and 3rd Tuesday of the month at 8:00pm EST, "
            "January through May 2026.\n\n"
            "Fee: $150 or School Tuition.\n\n"
            "Contact: butcher.casey@gmail.com."
        ),
    },
    {
        "title": "Introduction to the Big Other: The closing portion of Seminar II",
        "slug":  "introduction-big-other-2025-26",
        "faculty": [("Casey", "Butcher")],
        "start_date": date(2025, 9, 2),
        "end_date":   date(2025, 12, 31),
        "description": (
            "Dates and times: 1st and 3rd Tuesday of the month at 8pm EST, "
            "September through December 2025.\n\n"
            "Fee: $150 or School Tuition.\n\n"
            "Contact: butcher.casey@gmail.com."
        ),
    },
    {
        "title": "Graphing Desire, Writing Dreams",
        "slug":  "graphing-desire-writing-dreams-2025-26",
        "faculty": [("Diana", "Cuello")],
        "start_date": date(2025, 9, 5),
        "end_date":   date(2026, 5, 31),
        "description": (
            "Dates and times: monthly, September to May, 1st Fridays, "
            "12–2pm Eastern Standard Time.\n\n"
            "Fee: $500 or School Tuition.\n\n"
            "Note: CE credits are available for this seminar (2 per meeting).\n\n"
            "Contact: Diana Cuello, dianacuellophd@gmail.com."
        ),
    },
    {
        "title": (
            "The work of the letter in psychoanalysis: Freud's letters, "
            "Lacan's return to Freud, speech and writing in the clinic and "
            "School of psychoanalysis"
        ),
        "slug":  "work-of-the-letter-2025-26",
        "faculty": [("Christopher", "Meyer")],
        "start_date": date(2025, 9, 27),
        "end_date":   date(2026, 6, 27),
        "description": (
            "Dates and times: every 4th Saturday of the month except December, "
            "27 September 2025 through 27 June 2026, 10am–12 noon Pacific "
            "Standard Time.\n\n"
            "Fee: $60 per session / $40 students, or School Tuition.\n\n"
            "Contact: Christopher Meyer, PhD; (323) 930-9662; cmeyerwoeswar@gmail.com."
        ),
    },
    {
        "title": "Lacanian Clinical Practice — Dream, Symptom, Fantasy: a Clinical Cases Seminar",
        "slug":  "lacanian-clinical-practice-2025-26",
        "faculty": [("Christopher", "Meyer")],
        "start_date": date(2025, 10, 14),
        "end_date":   date(2026, 6, 9),
        "description": (
            "Dates and times: second and fourth Tuesdays of the month, "
            "14 October 2025 through 9 June 2026, 7–8:20pm Pacific Time. "
            "Break from December until classes resume January 13; no class "
            "April 8; classes resume April 22.\n\n"
            "Fee: $40 per meeting or School Tuition.\n\n"
            "Contact: Christopher Meyer, PhD; (323) 930-9662; cmeyerwoeswar@gmail.com."
        ),
    },
    {
        "title": "Introduction to Lacan: Basic Concepts",
        "slug":  "intro-to-lacan-basic-concepts-2025-26",
        "faculty": [("Marcelo", "Estrada"), ("Diana", "Dopchiz de Martin")],
        "start_date": date(2026, 1, 31),
        "end_date":   date(2026, 2, 7),
        "description": (
            "Dates and times: Saturday 31 January 2026 and Saturday 7 February "
            "2026, 10am–12pm Pacific Time.\n\n"
            "Fee: Donation to the school.\n\n"
            "Contact: Marcelo Estrada, marcelo.estrada@gmail.com; and "
            "Diana Dopchiz de Martin, ddmartinmft@gmail.com."
        ),
    },
]


WIX_DESCRIPTIONS = {
    "four-lessons-of-psychoanalysis-2025-26":
        """This seminar is a close reading of Moustafa Safouan’s (2004) Four Lessons of Psychoanalysis, which was edited by Anna Shane for Other Press.

We will meet over Zoom to collectively read Four Lessons of Psychoanalysis by Moustafa Safouan. Afterwards, we may free associate about what we just read.

Readings:

Safouan, Moustafa. Four lessons of psychoanalysis. Other Press, 2004.""",
    "graphing-desire-writing-dreams-2025-26":
        """Following Freud and Lacan, we will consider the dream as a rupture and writing of the unconscious from an Other scene, not as a narrative with a hidden meaning.  The seminar will consider the field of the Other and the place of the analyst in guiding the analysand to hear the rupture of a dream and its signifiers. The seminar will focus on Lacan’s graph of desire as a structuring logic for subject formation as well as a guide for psychoanalytic treatment.

Participants will present dreams from their patients/ analysands several times in the course of the seminar.  This is not a case study of the patient, but a case of the-analyst-in training working under constraints of the Lacanian clinic and transference.  Presenters will focus on signifiers as traces of dreams and explain their interventions in the unfolding dream work, following the effects of the interventions over time.

Respecting the limits of language and the unknown unsayable that comes with dreams, we will listen to the presenter in the place of the analyst speaking to the logic that is at work in her or his interventions. The aim of the seminar is to develop a series of writings ending with a condensed 10-minute writing that highlights the dream logic.

As a condition of joining the seminar, everyone will sign a confidentiality agreement. Limited to 12 participants presenting cases with dreams.

This seminar will consist of short lectures, activities and participant presentations. This is writing intensive course and participants will be expected to present from either their case material or the readings each time we meet.

Readings:

Please read or re-read the following foundational texts prior to our first meeting.

Freud, S. (1915-16). The Standard Edition of the Complete Psychological Works of Sigmund Freud, Volume XV: Introductory Lectures on Psycho-Analysis (Part II).

Freud, S. (1933). New Introductory Lectures On Psycho-Analysis. The  Standard Edition of the Complete Psychological Works of Sigmund Freud,  Volume XXII (1932-1936): New Introductory Lectures on Psycho-Analysis and Other Works, Lecture XXIX Revision of the Theory of Dreams (pages 6-29).

Additional readings will be added monthly during the year.  I will continue to draw from Ecrits and Seminar V.

Lacan, J. (2007). Ecrits (B. Fink, Trans.). WW Norton.

Lacan, J. (1998). Seminar 5-Formations of the unconscious. (R Grigg, Trans.). WW Norton.""",
    "intersubjectivity-otherness-position-2025-26":
        """Despite its imaginary aspects, such as reciprocity, mutuality, and symmetry, the notion of intersubjectivity-extensively explored by Edmund Husserl in phenomenology- represents an attempt to grapple with the question of the other for the subject and the nature of otherness in subjective experience. It unveils an alienated dimension within subjectivity that resists complete assimilation into or reduction to a self-centered framework. Lacan situates the fundamental role of speech and language within this field, emphasizing the intersubjective nature of speech and the transindividual character of the unconscious. While Lacan critiques this notion for its ties to the imaginary in the 1960s, he nevertheless maintains that the irreducible dimension of otherness remains crucial. In Lacanian psychoanalysis, otherness is not confined to the structural field of language but is brought into the analytic process through the desire of analysis. It is the analyst’s desire that instills a radical otherness into the analysis, thereby echoing Freud’s assertion that self-analysis is impossible.

This seminar, conducted in Chinese, will approach the topic by first engaging with Husserl’s work to examine how the question of the other is articulated. We will then explore Lacan’s writings, which demonstrate that the field of otherness is necessary for the subject—not only experientially and structurally but also logically. Finally, we will focus on the clinical implications of these ideas, particularly the position of the analyst and the role of the analyst’s desire in the analytic process.

This Chinese speaking seminar will be grounded in the study of key literature, though dedicated reading time will be limited. The majority of our sessions will consist of my commentary on the texts, accompanied by lectures exploring the central themes and ideas they address. Seminar participants will be encouraged to engage deeply through open-ended discussions.

Readings:

Lacan, J.  “The Function and Field of Speech and Language in Psychoanalysis” Écrits, (2001). Trans. Bruce Fink. New York: Norton.

Lacan, J.  “Logical Time and the Assertion of Anticipated Certainty” Écrits, (2006). Trans. Bruce Fink. New York: Norton.

Husserl, E. “Fifth Meditation. Uncovering of the Sphere of Transcendental Being as Monadological Intersubjectivity” Cartesian Meditations: an Introduction to Phenomenology, (1982). Trans. Dorion Cairns. The Hague: Martinus Nijhoff Publishers.

Laplanche, J.  “Transference: its Provocation by the Analyst” Essays on Otherness, (1999). Trans. Luke Thurston. London and New York: Routledge.

Neill, C. “Breaking the text: An Introduction to Lacanian discourse analysis.” Theory & Psychology 23.3 (2013): 334-350.

Fink, B.  “Desire in Analysis” A clinical introduction to Lacanian psychoanalysis: Theory and technique Harvard University Press, 1999.""",
    "intro-to-lacan-basic-concepts-2025-26":
        """Introduction to Lacan: Basic Concepts

This two-day seminar provides an overview of Lacan's fundamental theoretical concepts and does not presuppose prior familiarity with Lacanian theory. After providing an overview of Lacan's life and seminal influences on his work the instructors will introduce the theory of the signifier to explain Lacan's theory of the unconscious and of desire, and the formation of the subject. A presentation of the registers of the Real, Imaginary, and Symbolic will serve as background for a review of other seminal concepts, such as Lacan's view of narcissism, identification, and the drive, as well as the distinctions between pleasure and jouissance.""",
    "introduction-big-other-2025-26":
        """Introduction to the Big Other: The closing portion of Seminar II

In this seminar, we will continue to retrace the signifying chain of Lacan’s early seminar, reading aloud and discussing one lecture therefrom each time we meet. Between sessions, participants will be encouraged to read the texts Lacan cites. By proceeding this way, we will revisit Freud’s writings impacted by the effects of an encounter with the symbolic apparatus of Lacan’s teaching and our own speaking in session. Those who are practicing are invited to share any clinical material that resonates with what emerges in our readings and conversations. We’ll pick up in Seminar II about 2/3 of the way through, where we left off in May 2025. Previous participation is not a requirement to join. All are welcome.

Readings:

Freud, S. Selections from The Standard Edition of the Complete Psychological Works of Sigmund Freud. Ed. J. Strachey.

Lacan, J.  The seminar of Jacques Lacan, Book 2: The Ego in Freud’s Theory and in the Technique of Psychoanalysis – 1954-1955, (1991). Trans. S. Tomaselli. WW Norton & Company.""",
    "lacan-seminars-xxiii-xxiv-2025-26":
        """Lacan Seminars XXIII and XXIV (1975—‘77 ):  On love, unknown knowing and the failure that takes flight

... and what now?  What to do when the bindings come undone, and there’s no longer any authority to appeal to?  When the symbolic has floated free of the imaginary and the real, Lacan taught, psychoanalysis provides a mending:  the symptom itself.  Refashioned via our practice, the symptom can itself relink the registers, help them to go on, even when—due to whatever mistakes—there’s no longer anything holding them together.

Only the talking cure can fashion a savoir-faire, a know-how or artifice able to endow, as he put it, a remarkable quality to the art of which one is capable.  From the twin poles of the body and language, a real accord; from a babble of tongues, an élan... this art can even, faced with the void of a failed paternity, knot a four-leaf clover out of a broken Trinity.

Only our practice—centered on the equivocity of speech, engaging in, to cite Steiner’s words describing the sinthome of James Joyce, collages of word-play, macaronics or acrostics—opens avenues to the understanding and pleasure derived from that tensed imbalance between the expected and the shock of the new which is itself, at its finest, a shock of recognition, a déja vu... only this practice can take us home to that we didn’t know we knew.

We’ll spend this year in a close line-by-line reading of Lacan’s Seminars XXIII (1975— ‘76):  The Sinthome and XXIV (1976—’77):  L’insu que sait de l’une-bévue s’aile à mourre in English translation, alongside French versions of the texts.

Sessions consist of reading the seminars aloud for one hour by seminar participants, each consecutive session of Lacan’s seminars corresponding to one meeting, followed by an hour of free association, exploration, analysis and exegesis.

Readings:

Lacan, J.  The Seminar of Jacques Lacan, Book XXIII:  The Sinthome, (2016).  Trans. A.R. Price.  Cambridge, UK:  Polity.

Additional online readings to be assigned.""",
    "lacanian-clinical-practice-2025-26":
        """Lacanian Clinical Practice, Dream, Symptom, Fantasy:  a Clinical Cases Seminar

The logic and experience of this seminar proposes and assumes a methodology and a praxis: our reading of Freud focuses on the ways in which Lacan’s teaching in his seminar and writing in the Écrits transmits a savoir that orients clinical practice insofar as it welcomes the dream, symptom and unconscious formations as they break through as representative of  a censored unconscious.  We begin with the question of how the position of the analyst in Lacanian clinical practice creates a frame for the work of the unconscious as it manifests in the speech of the analysand.

As participants in the seminar present their cases, our work will be oriented by moments in which unconscious formations make a rupture in the ego’s discourse, and articulate the position of the subject of the unconscious in relation to desire and jouissance.

Readings:

Freud, S. (1900).  The Interpretations of Dreams, Volume IV, The Standard Edition of the Complete Psychological Works of Sigmund Freud

Freud, S (1917). “The Sense of the Symptom,” Volume XI, The Standard Edition of the Complete Psychological Works of Sigmund Freud.

Lacan, J. (1991).  The Seminar of Jacques Lacan, Book II, The Ego in Freud’s Theory and in the Technique of Psychoanalysis, 1954-1955.  Trans. Sylvana Tomaselli.  New York:  Norton.

Lacan, J.  (2006). “The Direction of the Treatment and the Principle of its Power,” Écrits, (2006). Trans. Bruce Fink. New York: Norton.""",
    "psychoanalytic-training-2025-26-part-7":
        """“The goal of my teaching has always been, and remains, to train analysts.”

What does it take to train as a Lacanian psychoanalyst? Lacan’s famous return to the truth of Freud is a major critique of what has gone wrong with Psychoanalysis. Freud’s students have deviated from the radical core of Freud’s work and regressed to what Lacan had characterized many a time as a return to “General Psychology.” Lacan’s return to Freud is nothing short of a proposal for analytic training that is true to the spirit of the unconscious, to an ethics indicated by desire and later by the drive.

At the heart of this training—from one’s analysis, control analysis, attending seminars, organizing and participating in cartels, teaching, la passe, and being involved in the activities of the School—is the question of whether or not one finally gets to assume the analytic position, the discourse of the analyst, and continues to be involved in the many aspects of the transmission of the truth of Lacan and Freud.

It has been said, and Lacan said so himself, that most of his seminars and writing are about training analysis.

This project involves not just the usual reading and familiarizing with Lacanian concepts—for example, the Imaginary, Symbolic and Real—but reading these categories to analyze how they guide and inform the training, technique, and practice of analysis. Therefore, we will go through some of Lacan’s writing and seminars, from the early to late Lacan.

This year-round seminar is designed to help candidates and precandidates as they traverse their singular journey to becoming a Lacanian-Freudian psychoanalyst.

Readings will be announced a month before the start of the seminar.""",
    "reading-seminar-viii-2025-26":
        """Reading Lacan’s Seminar Book VIII: Transference

In this year’s seminar, we will read Lacan’s Seminar VIII: Transference. At this stage of his work, Lacan’s approach is deeply rooted in structural analysis. Love, desire, and transference are all understood as structures.

Transference is one of the most fundamental concepts in psychoanalysis. Wherever there is a subject, there is transference, and this is closely connected to a premise: the subject and the signifier share an “initial,” “inaugural,” and “logical” connection. The signifying chain of the unconscious constructs the speaking subject.

Transference lies at the core of the affects between the analyst and the analysand. This is why Lacan begins Transference with “In the Beginning Was Love.” After all, without love, who would like to go into analysis?

Analysts are often seen as cold and silent, but this isn’t the whole story. The analyst’s emotional presence is revealed in the cut—the act of cutting, of stopping the subject’s endless sliding along the chain of signifiers. Analysis is a creative act,  and a risky one, since transference can take effect at any moment.

We will have a close reading of the seminar together with a free associative open-ended discussion.

Readings:

Lacan, Jacques. The Seminar of Jacques Lacan Book VIII: Transference. Trans. Bruce Fink. Cambridge: Polity Press, 2015.""",
    "secretaries-psychotic-subject-2025-26":
        """In this seminar, we will continue to retrace the signifying chain of Lacan’s early seminar, reading aloud and discussing one lecture therefrom each time we meet. Between sessions, participants will be encouraged to read the texts Lacan cites. By proceeding this way, we will revisit Freud’s writings impacted by the effects of an encounter with the symbolic apparatus of Lacan’s teaching and our own speaking in session. Those who are practicing are invited to share any clinical material that resonates with what emerges in our readings and conversations. All are welcome.

Readings:

Freud, S. Selections from The Standard Edition of the Complete Psychological Works of Sigmund Freud. Ed. J. Strachey.

Lacan, J.  The seminar of Jacques Lacan, Book 3: The Psychoses – 1955-1956, (1993). Trans. R. Grigg. WW Norton & Company.

Schreber, D.P. Memoirs of My Nervous Illness. Trans. I. Macalpine & R. A. Hunter. New York Review of Books.""",
    "work-of-the-letter-2025-26":
        """The work of the letter in psychoanalysis:  Freud’s letters, Lacan’s return to Freud, speech and writing in the clinic and School of psychoanalysis

This seminar explores the centrality of the letter in the history and experience of psychoanalysis as a rupture in the episteme of the speaking-being.  A consideration of the letter takes us to the heart of  what is at stake in the transmission  of a  subject’s truth and knowledge as regards the unconscious.  As we read Freud’s early letters to Wilhelm Fliess we witness a sustained correspondence and even a working through of an imaginary transference for Freud.  Even as Freud undergoes his disillusionment of this transference, these letters establish an address for Freud that concerns his discovery of a censored as well as a repressed unconscious.  And the address will be sustained throughout the remainder of his written work, or what we now refer to as Freud’s Standard edition.

The seminar argues that Freud’s address will await Lacan’s return address, his return to Freud, to restore the practice of the letter as one of an inscription that repeats and insists in the life of the subject who is represented by and through the signifier.  Lacan’s return to Freud results in a move from the man of letters, or the transmission of psychoanalysis through the question of the written and what can be written about it, to a consideration of the letters of the body as inscriptions of the Real, of jouissance, that select signifiers representing a subject to a Real unconscious.

The seminar takes the form of a lecture and reading group format.  Participants will also be asked to take up an epistolary correspondence with a fellow seminar participant as we make our way throughout the year as a way of engaging in a written record of what arises over the course of its experience.

Readings:

Certeau, Michel de. (2000).  “Lacan:  an ethics of speech,” Heterologies:  discourse on the other.   Trans., Marie-Rose Logan, Minneapolis, University of Minnesota Press.

Freud, S. (1995).  The Complete Letters of Sigmund Freud to Wilhelm Fliess, 1887-1904.  Translated and edited by Jeffrey Moussaieff Masson.  Cambridge:  Harvard University Press.

Freud, S. Selections from The Standard Edition of the Complete Psychological Works of Sigmund Freud. Ed. J. Strachey.

Lacan, J. (2006). “The Instance of the Letter in the Unconscious or Reason Since Freud,” Écrits. (2006).  Trans. Bruce Fink, New York:  Norton.

Lacan, J.  Selections from the Seminars of Jacques Lacan,  Seminars XX, Encore, and Seminar XXI, Les Non-dupes Errent, 1973-1974.  Trans. C. Gallagher

Lacan, J. (1990).  “Founding Act,” in Television, A Challenge to the Psychoanalytic Establishment.  Trans. Denis Hollier, Rosalind Krauss, and Annette Michelson.  New York:  Norton.

Lacan, J. (1990).  “Letter of Dissolution,” in Television, A Challenge to the Psychoanalytic Establishment.  Trans. Denis Hollier, Rosalind Krauss, and Annette Michelson.  New York:  Norton.

Lacan, J. (1990).  “The Other is Missing,” in Television, A Challenge to the Psychoanalytic Establishment.  Trans. Denis Hollier, Rosalind Krauss, and Annette Michelson.  New York:  Norton.""",
}


def _merged_description(s: dict) -> str:
    """Wix prose (when available) above the metadata block from the importer."""
    wix = WIX_DESCRIPTIONS.get(s["slug"], "").strip()
    own = s["description"].strip()
    if wix:
        return f"{wix}\n\n---\n\n{own}"
    return own


def _find_user(first: str, last: str) -> User | None:
    qs = User.objects.filter(first_name__iexact=first, last_name__iexact=last)
    if qs.exists():
        return qs.first()
    qs = User.objects.filter(last_name__iexact=last)
    if qs.count() == 1:
        return qs.first()
    return None


class Command(BaseCommand):
    help = "Import the 2025-2026 academic year seminar program from the Wix site."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Mark imported events as published=True so they appear on /program/.",
        )

    def handle(self, *args, dry_run: bool, publish: bool, **opts):
        report = {"created": 0, "updated": 0, "skipped": 0, "unresolved_faculty": []}

        with transaction.atomic():
            for s in SEMINARS:
                faculty: list[User] = []
                missing = []
                for first, last in s["faculty"]:
                    u = _find_user(first, last)
                    if u:
                        faculty.append(u)
                    else:
                        missing.append(f"{first} {last}")
                if missing:
                    report["unresolved_faculty"].append((s["title"], missing))
                    self.stderr.write(self.style.WARNING(
                        f"  {s['title']}: unresolved faculty {missing}"
                    ))

                defaults = {
                    "title":       s["title"],
                    "description": _merged_description(s),
                    "event_type":  Event.Type.SEMINAR,
                    "format":      Event.Format.ONLINE,
                    "start_date":  s["start_date"],
                    "end_date":    s["end_date"],
                    "published":   publish,
                    "status":      Event.Status.OPEN if publish else Event.Status.DRAFT,
                }
                event, created = Event.objects.update_or_create(
                    slug=s["slug"], defaults=defaults,
                )
                event.faculty.set(faculty)
                report["created" if created else "updated"] += 1
                self.stdout.write(
                    f"  {'created' if created else 'updated'}: {event.slug} "
                    f"({len(faculty)} faculty)"
                )

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Would " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}create {report['created']}, update {report['updated']}. "
            f"{len(report['unresolved_faculty'])} title(s) had unresolved faculty."
        ))
