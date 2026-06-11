"""Seed the 2026-2027 academic year program from the LSP 2026-2027 Word doc.

One-shot management command (M12). Re-runnable; idempotent on (slug).

Task #245 (Reinhardt feedback): the source descriptions arrived as one
monolithic blob (prose + "Readings:" + a "---" tail of Faculty / Dates /
Location / Contact / Fee). Each entry is now split into the structured Event
fields — ``description`` (prose only), ``readings`` (one citation per line),
``schedule_note``, ``contact``, ``fee_note``, ``format`` — so the event page
can format them properly. Faculty names from the old tail live on the event
workgroup roster; the rest of the tail is preserved verbatim in its field
(obvious mechanical typos fixed; substantive oddities flagged in the task).
"""
# ruff: noqa: E501

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from events.models import Event

SEMINARS = [
    {
        "title": 'Das Unbehagen in der Kultur',
        "slug":  'das-unbehagen-2026-27',
        "faculty": [('Robert', 'Beshara')],
        "start_date": date(2026, 10, 1),
        "end_date":   date(2026, 10, 29),
        "event_type": Event.Type.SEMINAR,
        "description": """This seminar introduces a close reading of Freud’s 1930 treatise, exploring the structural antagonism between individual drive and the demands of the collective. In the current American political landscape, characterized by intensifying polarizations and the shifting boundaries of the commons, Freud’s insights into the cultural superego and the aggressive underside of communal bonds take on a renewed, albeit ambiguous, urgency. We will examine how the renunciation of drives—once considered the price of entry into civilization—is being renegotiated in a digital and fragmented social field.""",
        "readings": [
            "Freud, S. *Civilization and Its Discontents*, (2015). Trans. G. C. Richter. Broadview Press.",
        ],
        "schedule_note": "Thursdays, 5:00 PM – 7:00 PM Pacific Time. Weekly for 5 sessions, starting October 1st. Online via Zoom.",
        "contact": "besharaster@gmail.com",
        # Source doc had "[or school tuition?]" appended — tuition coverage is
        # pending PC confirmation (flagged in task #245).
        "fee_note": "$100 donation to the school encouraged, none turned away.",
    },
    {
        "title": 'Workshop for a Clinic of Psychosis',
        "slug":  'workshop-clinic-of-psychosis-2026-27',
        # NB: Richard's account has first_name="Richard Hoffman" — the tuple
        # must match it exactly or set_faculty() drops him from the roster.
        "faculty": [('Bret', 'Fimiani'), ('Richard Hoffman', 'Reinhardt'), ('Shanna', 'Carlson de la Torre')],
        "start_date": date(2026, 10, 3),
        "end_date":   date(2027, 4, 17),
        "event_type": Event.Type.SEMINAR,
        "description": """This workshop invites participants to collaborate in imagining future psychoanalytic clinics of psychosis. Guided by an ethics that respects speech and understands that results follow from it, we ask: What can be built, and with what tools?

Over the course of fourteen meetings from October through April, we will explore central themes involved in establishing and sustaining clinics of psychosis.

Key areas of focus will include: the roles of geography and place; the forms of collaboration necessary within treatment teams (including questions of metapsychological orientation, training, supervision, and licensure); issues of financial sustainability and clinic structure (individual practice; group practice; hybrid forms); responses to crisis; and questions of autonomy and public-facing work.

Many meetings will feature either guest speakers or roundtable discussions with analysts, clinicians, and researchers currently involved in the development and running of Lacanian and post-Lacanian clinics of psychosis; the other meetings will be devoted to working together with what we have heard and to discussing assigned readings.

Guest presenters confirmed so far include: Felix Acuña Olivos (formerly Rayo); Barri Belnap, MD; Hannah Bennett; Marisa Berwald; Loren Dent (Constellations); Gardner Fair; Bret Fimiani; Daniel Garcia (The MendCenter); Christopher Meyer; Matthew Oyer (Constellations); Richard Reinhardt (Openings); Annie Rogers

Through engaging with guest presentations, roundtable discussions, and readings, workshop participants will work towards their own proposals for a future clinical project, to be presented in the final meetings of the workshop.

Prospective participants are asked to reach out to the faculty facilitators at lsppsychosisworkshop@gmail.com with a brief description of their desire and interest to work together on questions related to the creation of a clinic of psychosis.""",
        # Description + readings were refined in prod admin after the first
        # import (2026-06) — this entry mirrors that richer version.
        "readings": [
            "Apollon, Willy. *Psychoses: L’offre de l’analyste*. GIFRIC, 1999. Excerpts.",
            "Apollon, Willy. “Le transfert du psychotique.” *Le traitement psychanalytique des psychoses: Sa clinique et ses résultats*, collectif sous la direction du Gifric, Éditions du Gifric, 2024, pp. 163-185.",
            "Apollon, Willy, Danielle Bergeron, and Lucie Cantin. \"The Treatment of Psychosis.\" *The Subject of Lacan: A Lacanian Reader for Psychologists*, edited by Kareen Ror Malone and Stephen R. Friedlander, State University of New York Press, 2000, pp. 209-227.",
            "Bergeron, Danielle. “De la crise à l'impasse dans la cure psychanalytique\" [“From Crisis to Impasse in the Psychoanalytic Cure\"]. *Santé mentale au Québec*, vol. 35, no. 2, 2010, pp. 13–29. Excerpts.",
            "Cantin, Lucie, Jeffrey S. Librett, and Tracy McNulty, editors. *A Psychoanalysis for a Reemergent Humanity: The Metapsychology of Willy Apollon*. State University of New York Press, 2025.",
            "Fimiani, Bret. “Towards a New Ethics.” *Psychosis and Extreme States: An Ethic for Treatment*, Palgrave Macmillan, 2021, pp. 103–135.",
            "Lacan, Jacques. “A Lacanian Psychosis: Interview by Jacques Lacan.” *Returning to Freud: Clinical Psychoanalysis in the School of Lacan*, edited and translated by Stuart Schneiderman, Yale University Press, 1980, pp. 19–41.",
            "Miller, Alexander Reid. “What Was the 388? Opening the Dossier.” *Psychoanalysis and History*, vol. 27, no. 2, 2025, pp. 203–221.",
            "Rogers, Annie G. “Hallucinated Bodies: Art and Its Alphabets in Psychosis.” *Incandescent Alphabets: Psychosis and the Enigma of Language*, Routledge, 2018, pp. 45-71.",
            "Rogers, Annie G. “Infinite Code: Clocks, Calendars, Numbers, Music, Scripts.” *Incandescent Alphabets: Psychosis and the Enigma of Language*, Routledge, 2018, pp. 73-101.",
            "Vanderwees, Chris. “Treating Psychosis in Québec: A Conversation with the Founders of GIFRIC and the 388.” *The Museum of Dreams*, translated by Daniel Wilson, Dec. 2019, The Museum of Dreams.",
        ],
        "schedule_note": "1st, 3rd, and 5th Saturdays, October 3, 2026 – April 17, 2027 (except December 19 and January 2), 9am-11:30am Pacific Time. Online.",
        "contact": "Garret Barnwell, Bret Fimiani, Richard Reinhardt, and Shanna Carlson de la Torre at lsppsychosisworkshop@gmail.com",
        "fee_note": "$500 or School Tuition.",
    },
    {
        "title": 'Reading Lacan’s Seminar Book VIII: Transference (II)',
        "slug":  'reading-seminar-viii-ii-2026-27',
        "faculty": [('Yang', 'Yu'), ('Cissy', 'Hong Zhou')],
        "start_date": date(2026, 9, 1),
        "end_date":   date(2027, 5, 31),
        "event_type": Event.Type.SEMINAR,
        "description": """We move on slowly. But this is the real tempo of psychoanalysis because the searching for truth, like what we experience in analysis, takes detours. So in this year’s seminar, we will continue to read Lacan’s *Seminar VIII: Transference*.

We read and we talk. In talking we associate from the text of Lacan, and when we associate we do not know the destination but the signifiers will bring us to it.""",
        "readings": [
            "Lacan, Jacques. *The Seminar of Jacques Lacan Book VIII: Transference*. Trans. Bruce Fink. Cambridge: Polity Press, 2015.",
        ],
        "schedule_note": "9:00-11:00 am (Beijing time), every third and fourth Wednesday each month, from September to May. Online.",
        "contact": "celavieglove@126.com; cissyhongzhou@126.com",
        "fee_note": "US $400 or school tuition.",
    },
    {
        "title": 'Sounding Out the Signifier: Lacan, Freud, and the Rat Man',
        "slug":  'sounding-out-the-signifier-2026-27',
        "faculty": [('Casey', 'Butcher'), ('John', 'Kreitzberg')],
        "start_date": date(2026, 9, 5),
        "end_date":   date(2027, 5, 1),
        "event_type": Event.Type.SEMINAR,
        "format": Event.Format.IN_PERSON,
        "description": """In this seminar, we will revisit Freud’s writing on his clinical work with Ernst Lanzer, a.k.a. The Rat Man, through the lens of Lacan’s theoretical elaboration of the case in “The Neurotic’s Individual Myth.” Further readings will bring to the fore the centrality of the signifier and the punning of reason in Lacanian clinical psychoanalysis and highlight this dimension of Freud’s own practice. We’ll explore psychoanalytic structural psychodiagnostics with an emphasis on the differential diagnosis between hysterical and obsessional neurosis, engage with a recent case history that shares some of the features of the Rat Man case, and explore the aim or ends of analysis as conceptualized by Lacan.

Our aim is to demystify and spark interest in Lacanian psychoanalytic practice and invite participants to consider how this tradition may inform their own. Toward this end, in addition to guided discussion of assigned readings, participants will be encouraged to share and discuss clinical work in relation to the material we read. As a condition of joining the seminar everyone will sign a confidentiality agreement. This seminar is limited to 12 participants.""",
        "readings": [
            "Freud, S. Notes Upon a Case of Obsessional Neurosis (1909) and other selections from *The Standard Edition of the Complete Psychological Works of Sigmund Freud*. Ed. James Strachey.",
            "Gessert, A. “What We Can Still Learn from the Rat Man” in *Freud’s Principle Case Studies Revisited* (2025). Eds. Helena Texier and Eve Watson. Routledge, (99-108).",
            "Lacan, J. Selections from *Écrits: The First Complete Edition in English* (2006). Trans. Bruce Fink. W. W. Norton & Company.",
            "Lacan, J. “The Neurotic's Individual Myth,” Trans. Martha Noel Evans. *Psychoanalytic Quarterly* (1979), vol. 48. Routledge, (pp.405-425).",
            "Lévi-Strauss, C. Selections from *Structural Anthropology* (1963). Trans. Claire Jacobson and Brooke Grundfest Schoepf. New York: Basic Books, Inc.",
            "de Saussure, F. Selections from *Course in General Linguistics* (1915). Trans. Roy Harris. Chicago: Open Court Classics.",
            "Rogers, Annie. “Surprising Sounds” in *The Unsayable* (2007). New York: Ballantine Books, (pp. 97-210).",
            "Verhaeghe, Paul. Selections from *On Being Normal and Other Disorders: A Manual for Clinical Pscyhodiagnostics* (2004). Trans. Sigi Jottkandt. New York: Other Press.",
            "Further readings will be added from time to time throughout the year.",
        ],
        "schedule_note": "First Saturday of the month, September 2026-May 2027, 11am-1pm EST. January meeting will instead be held on 1/9/27 and May meeting will be held on 5/8/27. In person in Philadelphia, PA; exact location TBD.",
        "contact": "butcher.casey@gmail.com & jkreitzbergpsych@gmail.com",
        "fee_note": "$500 or LSP tuition.",
    },
    {
        "title": 'Secretaries to the Psychotic Subject – Seminar III continued',
        "slug":  'secretaries-psychotic-subject-2026-27',
        "faculty": [('Casey', 'Butcher')],
        "start_date": date(2026, 9, 1),
        "end_date":   date(2027, 5, 19),
        "event_type": Event.Type.SEMINAR,
        "description": """In this seminar, we will continue to retrace the signifying chain of Lacan’s early published seminar, reading aloud and discussing one lecture therefrom each time we meet. Between sessions, participants will be encouraged to read the texts Lacan cites. By proceeding this way, we will revisit Freud’s writings impacted by the effects of an encounter with the symbolic apparatus of Lacan’s teaching and our own speaking in session. Those who are practicing are invited to share any clinical material that resonates with what emerges in our readings and conversations. As a condition for participation, all will sign a confidentiality agreement. We will pick up in Book III - The Psychoses where we left off in June 2026 - about halfway through, but previous participation is not required to join. Upon concluding the seminar (sometime in the winter of 2027), we will move to reading and discussion of more contemporary writing on the Lacanian clinic of psychosis.""",
        "readings": [
            "Freud, S. Selections from *The Standard Edition of the Complete Psychological Works of Sigmund Freud*. Ed. J. Strachey.",
            "Lacan, J. (1993). *The Seminar of Jacques Lacan, Book 3: The Psychoses – 1955-1956*. Trans. R. Grigg. WW Norton & Company.",
            "Schreber, D.P. (2000). *Memoirs of My Nervous Illness*. Trans. I. Macalpine & R. A. Hunter. New York Review of Books.",
            "Further readings will be added upon our completion of Seminar III.",
        ],
        "schedule_note": "1st and 3rd Tuesday of the month at 8:00pm-10pm EST, September 2026 through May 2027. There will be no meeting on the 3rd Tuesday of December. On Zoom.",
        "contact": "butcher.casey@gmail.com",
        "fee_note": "$200 or school tuition.",
    },
    {
        "title": 'Graphing Desire, Writing Dreams',
        "slug":  'graphing-desire-writing-dreams-2026-27',
        "faculty": [('Diana', 'Cuello')],
        "start_date": date(2026, 9, 4),
        "end_date":   date(2027, 5, 7),
        "event_type": Event.Type.SEMINAR,
        "description": """Following Freud and Lacan, we will consider the dream as a rupture and writing of the unconscious from an Other scene, not as a narrative with a hidden meaning. The seminar will consider the field of the Other and the place of the analyst in guiding the analysand to hear the rupture of a dream and its signifiers. The seminar will focus on Lacan’s graph of desire as a structuring logic for subject formation as well as a guide for psychoanalytic treatment.

Participants will present dreams from their patients/ analysands several times in the course of the seminar. This is not a case study of the patient, but a case of the-analyst-in training working under constraints of the Lacanian clinic and transference. Presenters will focus on signifiers as traces of dreams and explain their interventions in the unfolding dream work, following the effects of the interventions over time.

Respecting the limits of language and the unknown unsayable that comes with dreams, we will listen to the presenter in the place of the analyst speaking to the logic that is at work in her or his interventions. The aim of the seminar is to develop a series of writings ending with a condensed 10-minute writing that highlights the dream logic.

As a condition of joining the seminar, everyone will sign a confidentiality agreement. Limited to 12 participants presenting cases with dreams.""",
        "readings": [
            "Please read or re-read the following foundational texts prior to our first meeting.",
            "Freud, S. (1915-16). *The Standard Edition of the Complete Psychological Works of Sigmund Freud, Volume XV: Introductory Lectures on Psycho-Analysis (Part II)*.",
            "Freud, S. (1933). *New Introductory Lectures On Psycho-Analysis*. *The Standard Edition of the Complete Psychological Works of Sigmund Freud, Volume XXII (1932-1936): New Introductory Lectures on Psycho-Analysis and Other Works*, Lecture XXIX Revision of the Theory of Dreams (pages 6-29).",
            "Additional readings will be added monthly during the year. I will continue to draw from *Ecrits* and Seminar V.",
            "Lacan, J. (2007). *Ecrits* (B. Fink, Trans.). WW Norton.",
            "Lacan, J. (1998). *Seminar 5-Formations of the unconscious*. (R Grigg, Trans.). WW Norton.",
        ],
        "schedule_note": "Monthly, September to May, 1st Fridays, 12-2pm Eastern Standard Time. On Zoom, by invitation.",
        "contact": "Diana Cuello at dianacuellophd@gmail.com",
        "fee_note": "$500.00 or School Tuition.",
    },
    {
        "title": 'The Logic of Phantasy and the Psychoanalytic Act:  Lacan Seminars XIV and XV (1966—’68)',
        "slug":  'logic-of-phantasy-xiv-xv-2026-27',
        "faculty": [('Benjamin', 'Davidson')],
        "start_date": date(2026, 9, 9),
        "end_date":   date(2027, 5, 31),
        "event_type": Event.Type.SEMINAR,
        # The source blob also carried a stale schedule line from a prior flyer
        # ("beginning 7 January, 2026 ... Free-of-charge") that contradicted the
        # canonical tail (beginning 9 September 2026) — dropped here.
        "description": """We are living in an area of civilization where, as they say, there is free speech, namely that nothing of what you say is of any consequence.  You can say anything whatsoever about someone who may well be at the origin of some indicipherable murder or other:  you can even create a play about it.  The whole of America ... crowds into it.  Never previously in history would such a thing have been conceivable without the theater being immediately closed.  In the land of liberty one can say anything, because this has no consequences... we have even seen psychoanalysts questioning the future of the trade.
So Lacan, 1968:  The truth is fractured.  Me, the truth, I speak
...in the two years between these resonant utterances Lacan undertook, as the watershed of May ’68 approached, a search for models that would advance, with the most discrete steps, away from refined or renewed forms of positivism towards what he called exercises of skepticism.  This (re)search would take up, he said, the misunderstandings and fragmentary things, still so alive, that tradition has bequeathed to us—not simply as brilliant jugglings between opposed doctrines but as veritable spiritual exercises, corresponding to an ethical praxis, imposed by the clinic.  He sought, as do we Lacanians today, a rubric that would give veritable density to the theory that remains to us.
This search reached its apotheosis in the forging of a radical ‘algorithm’ that aimed to articulate the logic always at work, between a divided subject and the object cause of desire, in the mixed blood of conscious and unconscious scenarios, originary fantasies, grammatical transformations and infinite substitutions, myths, drives, history....
What does it mean to act psychoanalytically, and what is the logic of the psychoanalytic act?  How does acting out inhere in repetition, and how does analytic play diverge from alienation and passage-à-l’acte, where a subject might fall, as Lacan says, off the stage and into the world?
We’ll spend the next two years in a close line-by-line reading and discussion of Lacan’s Seminars XIV (1966— ‘67) and XV (1967— ‘68):  *The Logic of Phantasy and The Psychoanalytic Act* in English translation, alongside French versions of the texts.

Enrollment limited.""",
        "readings": [
            "Lacan, J. *Seminar Books XIV and XV* (Cormac Gallagher, transl). Additional readings as suggested.",
        ],
        "schedule_note": "Biweekly, Wednesdays 5—7 pm Pacific Time beginning 9 September, 2026. Online.",
        "contact": "benjamdavidson@me.com",
        "fee_note": "Donation to LSP encouraged, none turned away.",
    },
    {
        "title": 'The Topology of Lacan’s “Direction of Treatment”',
        "slug":  'topology-direction-of-treatment-2026-27',
        "faculty": [('Gardner', 'Fair')],
        "start_date": date(2026, 9, 12),
        "end_date":   date(2027, 5, 8),
        "event_type": Event.Type.SEMINAR,
        "description": """“The Direction of Treatment and the Principles of its Power” is Lacan’s most explicit writing on clinical work where he criticizes his contemporaries for reversing Freud’s direction of treatment.  For Lacan, remaining true to Freud would be to begin with what Lacan calls the “rectification of the real,” thereby opening the way for transference and, subsequently, a bold interpretation.  Lacan accuses his contemporaries of inverting this direction by starting instead with weak interpretations, waiting for a transference to develop, and then slowly liquidating it through encouraging the analysand’s identification with their reality tested, securely attached ego.
Lacan’s polemic is directed specifically against the 1956 collection of articles in *La Psychanalyse d’aujourd’hui*.  While familiarizing ourselves with this background material, we will more vigorously test Lacan’s claims against our own contemporaries.  Following Thomos Svolos’s *Twenty-First Century Psychoanalysis*, we will examine a clinical case of Thomas Ogden.  Expanding on Svolos’s analysis with the help of Stijn VanHeule, we will consider from a Lacanian perspective the more general treatment recommendations of Nancy McWilliams and Jonathan Shedler, two key authors of the *Psychodynamic Diagnostic Manual*.
To orient ourselves, each class will begin with a brief review of Lacan’s Graph of Desire drawing on topologies from Lacan’s Seminars IX, X and XI.  The floor will then be opened for students to present their own clinical material while working through the week’s reading, focusing especially on selected citations from Lacan.
Throughout, we will examine the clinical perils of drawing boundaries between Freud’s alleged standard direction of treatment, its acceptable variations, and its unacceptable deviations.""",
        "readings": [
            "Lacan, J.  “The Direction of Treatment and the Principles of its Powers,” *Écrits*, (2006). Trans. Bruce Fink. New York: Norton (pp. 489-542).",
            "Secondary",
            "McWilliams, N and Shedler, J. “Personality Styles and Disorders – P Axis,” (2026).  In *Psychodynamic Diagnostic Manual: (PDM-3)*, USA: Guilford Press, (pp. 651-708).",
            "Ogden, T. “The Analytic Third: Working with Intersubjective Clinical Facts,” *Subjects of Analysis*, (1994), USA: Jason Aronson Inc. (pp. 61-95).",
            "Shedler, J.  “Integrating clinical and empirical approaches to personality: The Shedler-Westen Assessment Procedure (SWAP),” (2022). In R.E. Feinstein (Ed.), *Personality Disorders*. Oxford: Oxford University Press (pp. 87-108).",
            "Svolos, T.  “Introducing the Symptom,” “Introducing the new symptoms,” and “Countertransference is the symptom of the analyst,” *Twenty-First Century Psychoanalysis*, (2018). New York: Routledge (pp. 71-81, 113-125, 207-220).",
            "VanHeule, S. “In between the signifier and the Real: On depressive experiences,” in *Lacan on Depression and Melancholia*, (2023), Eds. Derek Hook and Stijn VanHeule.  New York: Routledge, (pp. 29-40).",
        ],
        # Source said "running through May 2026" — corrected to 2027 (matches
        # the event's end date).
        "schedule_note": "The 2nd Saturday of each month, 9 am – 11 am Pacific Time, beginning September 12th 2026, skipping October, running through May 2027. Online.",
        "contact": "gardnerfair@yahoo.com",
        "fee_note": "$200 or School Tuition.",
    },
    {
        "title": 'The Clinic of the Death Drives',
        "slug":  'clinic-of-the-death-drives-2026-27',
        "faculty": [('Christopher', 'McCann'), ('Stephen', 'Mosblech')],
        "start_date": date(2027, 1, 17),
        "end_date":   date(2027, 6, 20),
        "event_type": Event.Type.SEMINAR,
        "description": """This peer consultation seminar takes as its crux the radical shift in psychoanalytic theory instantiated by *Beyond the Pleasure Principle* (1920) and its introduction of the death drives (notably plural in the original German Todestriebe). We will engage in a close reading of the Freudian text alongside clinical case discussion, exploring how the death drives operate as fundamental dynamics (de)structuring subjective experience. Particular emphasis will be given to the unique rhythm(s) of repetition - traumatic, uncanny, ludic or otherwise. Supplemental readings from Lacan’s Four Fundamental Concepts will be considered. Participants will be invited to present case material on moments of repetition, impasse, and insistences—or other themes that emerge from our reading. This seminar is designed for clinicians already seeing patients who wish to deepen their engagement with analytic technique and expand their capacity to work with  the death drives and repetition in clinical practice. Limited to 8 participants.""",
        "readings": [
            "Freud, S. *Beyond the Pleasure Principle*, (1920), *The Standard Edition of the Complete Psychological Works of Sigmund Freud*, Volume XVIII.",
            "Lacan, J. *The Seminar of Jacques Lacan, Book XI: The Four Fundamental Concepts of Psychoanalysis*, (1998), Ed. Jacques-Alain Miller, Trans. Alan Sheridan. New York: Norton.",
        ],
        "schedule_note": "Third Sunday of the month, January 2027 – June 2027, 10:00am-12:00pm ET. Virtual (Zoom).",
        "contact": "smosblech@proton.me",
        "fee_note": "$100 donation to the school encouraged, none turned away.",
    },
    {
        "title": 'Beyond Principle; or Put A Socket In It: Reading Lacan, Seminars I & II, 1953-1955',
        "slug":  'beyond-principle-2026-27',
        "faculty": [('Matthew', 'Seidman')],
        "start_date": date(2026, 9, 28),
        "end_date":   date(2027, 6, 28),
        "event_type": Event.Type.SEMINAR,
        "description": """A year-long, bi-weekly seminar, reading Lacan’s first two Seminars. Beginning again.

Each session will be a chapter of the Seminar. This will not be a reading-aloud-together class – rather, each is expected to have read, and – following a mode in this early Lacan – each session will – usually – begin with a participant presenting questions and thoughts about the chapter.

We will also read in their entirety Freud’s *Beyond The Pleasure Principle*; and – aloud, together – Sophocles’ *Oedipus At Colonus*.

It is notable that Lacan, in these first, foundational, remarkable teachings, is at play in the metaphors of light and reflection – and ends, almost thirty years later – like Oedipus himself – in haptic blindness, feeling his way with his hands, signifying with string. Like Oedipus – his end audible in this, his beginning.

We read – we are – within the veil of ‘our time’, in which the signifier – structurally empty – is evacuated of this emptiness – thereby making speech expulsion of the other from the contract of sense making. A symptom of Capitalist discourse, yes – but not only:
An enlisting of the signifier into the function (already nascent) of suicide vest – speech as detonation destroying communal agreements of meaning.
This the regime of the demand of the drive:  to eliminate difference.
The fissure that is difference is, as a legacy, lived as identity:  the mass found in the scan of the person known as ego.
So, in such a time – ours – a return to the initial caustic applied to the seeming substantiality of that mass, which was Lacan’s return to the letter of Freud.
A threshold, as was Seminar III, to psychosis – here in ‘our time’.
Towards tuning an analyst’s ears to a register of speech as solvent – a hearing speaking – these two Seminars are exemplars.""",
        "readings": [
            "Lacan, Jacques. *The Seminar of Jacques Lacan, Book I. Freud’s Papers On Technique, 1953-1954*. Trans. John Forrester. New York:  Norton, 1988.",
            "Lacan, Jacques. *The Seminar of Jacques Lacan, Book II. The Ego in Freud’s Theory and in the Technique of Psychoanalysis, 1954-1955*. Trans. Sylvia Tomaselli. New York:  Norton, 1991.",
            "Freud, S. *Beyond The Pleasure Principle*. Trans. James Strachey. New York:  Norton, 1961.",
            "Sophocles. “Oedipus at Colonus,” in *Sophocles I*. Trans. David Greene. Chicago:  University of Chicago, 1991. (One of various translations.)",
        ],
        "schedule_note": "Every other Monday, 5-7 pm PT, 8-10 pm ET, 9/28/26 - 6/28/27. Virtual.",
        "contact": "half.outside.it@gmail.com",
        "fee_note": "$25/class or school tuition; none turned away.",
    },
    {
        "title": 'The Analyst’s Act and its Results',
        "slug":  'analysts-act-and-its-results-2026-27',
        "faculty": [('Christopher', 'Meyer')],
        "start_date": date(2026, 9, 26),
        "end_date":   date(2027, 6, 26),
        "event_type": Event.Type.SEMINAR,
        "description": """This seminar elaborates the consequences and results of a change in discourse resulting in the possibility of an analytic experience as one in which a space and time are given to speak about the ruptures the unconscious has made and continues to make in the lived experience of the speaking being. The seminar proposes that the Freudian rupture inaugurates a new social link, which Lacan will formally and logically define through his work on the “analytic discourse” in seminar XVII and following.

At the heart of this discourse, or in the position of the agent proper, is the position of the analyst and the analytic act itself as one that makes way for the subject of the unconscious as a barred subject. This seminar will work on the question of the “act” from the perspective of the psychoanalytic experience insofar as it concerns a desire and its cause, jouissance and its work and transformation, and the Thing at work in the life and being of the subject.""",
        "readings": [
            "Freud, S. Selections from *The Standard Edition of the Complete Psychological Works of Sigmund Freud*. Ed. J.Strachey.",
            "Lacan, J. (2006). “The Instance of the Letter in the Unconscious or Reason Since Freud,” *Écrits*. (2006). Trans. Bruce Fink, New York: Norton.",
            "Lacan, J. *Seminar XV, The Psychoanalytic Act*, 1967-1968. Trans., C. Ghallager.",
            "Lacan, J. Selections from the Seminars of Jacques Lacan, Seminars XVII, XIX, XX, *Encore*, and Seminar XXI, *Les Non-dupes Errent*, 1973-1974. Trans. C. Ghallager",
            "Lacan, J. (1990). “Founding Act,” in *Television, A Challenge to the Psychoanalytic Establishment*. Trans. Denis Hollier, Rosalind Krauss, and Annette Michelson. New York: Norton.",
            "Lacan, J. (1990). “Letter of Dissolution,” in *Television, A Challenge to the Psychoanalytic Establishment*. Trans. Denis Hollier, Rosalind Krauss, and Annette Michelson. New York: Norton.",
        ],
        "schedule_note": "Every 4th Saturday of the month September, November, January, March, May, and June, 2026 through 2027, beginning September 26, 10:00 am-12 noon Pacific Standard Time. Online via Zoom.",
        "contact": "Christopher Meyer, PhD, (323) 930-9662, cmeyerwoeswar@gmail.com",
        "fee_note": "$60.00 per session/$40.00 students, or LSP tuition.",
    },
    {
        "title": 'Psychoanalysis in its Place and Time: the analytic act and its production, a Los Angeles',
        "slug":  'psychoanalysis-place-and-time-la-2026-27',
        "faculty": [('Christopher', 'Meyer')],
        "start_date": date(2026, 10, 24),
        "end_date":   date(2027, 4, 24),
        "event_type": Event.Type.SEMINAR,
        "format": Event.Format.IN_PERSON,
        "description": """This seminar considers the analytic experience, or discourse, as one in which the analyst’s offer creates the conditions of possibility for the advent of a singular subject called upon to act in its place and time according to an ethics of desire, jouissance, and the work of the drive, or that thing set to work in the speaking being as subject to speech, language, and the excess, or jouissance. As an experience, psychoanalysis is necessarily linked to the ruptures made by unconscious formations.

The seminar will be organized around the topics of the work of the dream, the symptom, and the logic of fantasy as an articulation of the subject of the unconscious in relationship to desire and jouissance as they are set to work in the life of the speaking-being in their place and time. As an in-person seminar, each meeting of the seminar will offer a Freudian-Lacanian practitioner working in the greater Los Angeles area the opportunity to present their clinical work based upon their experience of the analytic encounter, or clinical engagement, as it relates to what Lacan referred to as “factor C,” or the cultural factor in his essay “The Function and Field of Speech and Language.”""",
        "readings": [
            "Freud, S. Selections from *The Standard Edition of the Complete Psychological Works of Sigmund Freud*. Ed. J.Strachey.",
            "Lacan, J. (2006). “The Function and Field of Speech and Language,” *Écrits*. (2006). Trans. Bruce Fink, New York: Norton.",
        ],
        "schedule_note": "4th Saturday of the month October, February, and April — October 24, February 27, 2027, and April 24, 2027, 10:00 am-12 noon Pacific Standard Time. In person; location TBD, mid-City Los Angeles, California.",
        "contact": "Christopher Meyer, PhD, (323) 930-9662, cmeyerwoeswar@gmail.com",
        "fee_note": "$60.00 per session/$40.00 students, or LSP tuition.",
    },
    {
        "title": 'Lacanian Clinical Practice, Dream, Symptom, Fantasy: a Clinical Cases Seminar',
        "slug":  'lacanian-clinical-practice-2026-27',
        "faculty": [('Christopher', 'Meyer')],
        "start_date": date(2026, 10, 13),
        "end_date":   date(2027, 6, 8),
        "event_type": Event.Type.SEMINAR,
        "description": """The logic and experience of this seminar proposes and assumes a methodology and a praxis: our reading of Freud focuses on the ways in which Lacan’s teaching in his seminar and writing in the *Écrits* transmits a savoir that orients clinical practice insofar as it welcomes the dream, symptom and unconscious formations as they break through as representative of a censored unconscious. We begin with the question of how the position of the analyst in Lacanian clinical practice creates a frame for the work of the unconscious as it manifests in the speech of the analysand.

As participants in the seminar present their cases, our work will be oriented by moments in which unconscious formations make a rupture in the ego’s discourse, and articulate the position of the subject of the unconscious in relation to desire and jouissance.""",
        "readings": [
            "Freud, S. (1900). *The Interpretations of Dreams*, Volume IV, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S (1917). “The Sense of the Symptom,” Volume XI, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Lacan, J. (1991). *The Seminar of Jacques Lacan, Book II, The Ego in Freud’s Theory and in the Technique of Psychoanalysis, 1954-1955*. Trans. Sylvana Tomaselli. New York: Norton.",
            "Lacan, J. (2006). “The Direction of the Treatment and the Principle of its Power,” *Écrits*, (2006). Trans. Bruce Fink. New York: Norton.",
        ],
        "schedule_note": "Second and fourth Tuesdays of the month, October 13, 2026 through June 8, 2027, 7-8:20 pm Pacific Time, with a break from December until classes resume January 12, and no class March 23. Online via Zoom.",
        "contact": "Christopher Meyer, PhD, (323) 930-9662, cmeyerwoeswar@gmail.com",
        "fee_note": "$40.00 per meeting, or LSP Tuition.",
    },
    {
        "title": 'Freud Reading Group',
        "slug":  'freud-reading-group-2026-27',
        "faculty": [('Nathan', 'Lupo')],
        "start_date": date(2026, 9, 13),
        "end_date":   date(2027, 5, 9),
        "event_type": Event.Type.READING_GROUP,
        "description": """“In April 1885, Sigmund Freud wrote to his fiancée that he had ‘almost completed an undertaking which a number of people, still unborn but fated to misfortune, will feel severely.’” Peter Gay (1988) begins his biography of Freud with this anecdote, and while he notes that Freud was referring to his future biographers, it isn't hard to read these words as a prescient remark on the effect psychoanalysis would have on civilization.

Freud was a remarkable thinker and an intrepid explorer of the human psyche. His discovery of the unconscious and the invention of psychoanalysis changed the world and yet some of the same people who claim to carry on the work of psychoanalysis continue to speak disparagingly of its founder.

While there is no perfect founding father, one cannot in good conscience practice what is called psychoanalysis without having spent time on the couch or having read what Freud had to say about it. Moreover, the best introduction to the work of Jacques Lacan is Freud himself.

Together, we'll explore Freud's theoretical papers, case studies and metapsychological texts. We’ll discuss the ways they challenge and inspire us and, importantly, how they inform our clinical practice.""",
        "readings": [
            "Freud, S. *A Case of Hysteria* (1905). Volume VII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S. “The Dynamics of the Transference,” (1912). Volume XII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S. “Recommendations for Physicians on the Psychoanalytic Method of Treatment,” (1912). Volume XII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S., “On Beginning the Treatment (Further Recommendations on the Technique of Psychoanalysis I),” (1913). Volume XII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud S. “Remembering, Repeating and Working Through (Further Recommendations on the Technique of Psychoanalysis II),” (1914). Volume XII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S. “Observations on Transference-Love (Further Recommendations in the Technique of Psychoanalysis III),” (1915). Volume XII, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S. *The Ego and the Id* (1923). Volume XIX, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "Freud, S. “A Child is Being Beaten,” (1919). Volume XIX, *The Standard Edition of the Complete Psychological Works of Sigmund Freud*.",
            "This will be a Reading Group. Readings should be completed prior to meetings.",
        ],
        # Source said "Starting September 8th" — corrected to the 13th (the
        # second Sunday of September 2026; the 8th is a Tuesday).
        "schedule_note": "Second Sundays, 9:00 a.m. - 11:00 a.m. Pacific Time, starting September 13th. Online via Zoom.",
        "contact": "nathanlupo@pm.me",
        "fee_note": "$250 or School Tuition.",
    },
    {
        "title": 'INTRODUCTION TO LACAN: BASIC CONCEPTS',
        "slug":  'intro-to-lacan-basic-concepts-2026-27',
        "faculty": [('Marcelo', 'Estrada'), ('Diana', 'Dopchiz de Martin')],
        "start_date": date(2027, 2, 6),
        "end_date":   date(2027, 2, 13),
        "event_type": Event.Type.SEMINAR,
        "description": """This two-day seminar provides an overview of Lacan’s fundamental theoretical concepts and does not presuppose prior familiarity with Lacanian theory. After providing an overview of Lacan’s life and seminal influences on his work the instructors will introduce the theory of the signifier to explain Lacan’s theory of the unconscious and of desire, and the formation of the subject. A presentation of the registers of the Real, Imaginary, and Symbolic will serve as background for a review of other seminal concepts, such as Lacan’s view of narcissism, identification, and the drive, as well as the distinctions between pleasure and jouissance.""",
        "readings": [],
        "schedule_note": "Saturday 02/06/2027 and 02/13/2027, 2PM – 4PM PST. On Zoom.",
        "contact": "Marcelo Estrada marcelo.estrada@gmail.com / Diana Dopchiz de Martin ddmartinmft@gmail.com",
        "fee_note": "$50 or School tuition.",
    },
]

def _find_user(first: str, last: str) -> User | None:
    """Match a faculty (first, last) tuple to an existing User account."""
    return User.objects.filter(
        first_name__iexact=first.strip(), last_name__iexact=last.strip(),
    ).first()


class Command(BaseCommand):
    help = "Seed the 2026-2027 academic-year program (events + faculty links). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report would-be changes; don't write to the DB.",
        )
        parser.add_argument(
            "--publish", action="store_true",
            help="Mark created/updated events as published=True (default keeps current value).",
        )

    def handle(self, *args, dry_run: bool, publish: bool, **opts):
        created = updated = 0
        unresolved = []  # (title, [missing_faculty])

        for s in SEMINARS:
            missing_faculty = []
            faculty_users = []
            for first, last in s["faculty"]:
                u = _find_user(first, last)
                if u:
                    faculty_users.append(u)
                else:
                    missing_faculty.append(f"{first} {last}")

            defaults = {
                "title": s["title"],
                "description": s["description"],
                "readings": "\n".join(s.get("readings") or []),
                "schedule_note": s.get("schedule_note", ""),
                "contact": s.get("contact", ""),
                "fee_note": s.get("fee_note", ""),
                "format": s.get("format", Event.Format.ONLINE),
                "start_date": s["start_date"],
                "end_date":   s["end_date"],
                "event_type": s["event_type"],
            }
            if publish:
                defaults["published"] = True

            if dry_run:
                exists = Event.objects.filter(slug=s["slug"]).first()
                verb = "would update" if exists else "would create"
                self.stdout.write(
                    f"  {verb}: {s['slug']} ({len(faculty_users)} faculty"
                    + (f", missing: {', '.join(missing_faculty)}" if missing_faculty else "")
                    + ")"
                )
                if missing_faculty:
                    unresolved.append((s["title"], missing_faculty))
                continue

            with transaction.atomic():
                event, was_created = Event.objects.update_or_create(
                    slug=s["slug"], defaults=defaults,
                )
                # Reconcile faculty as a role on the event's workgroup
                # (idempotent re-runs are predictable).
                event.set_faculty(faculty_users)

            if was_created:
                created += 1
                verb = "created"
            else:
                updated += 1
                verb = "updated"
            self.stdout.write(
                f"  {verb}: {s['slug']} ({len(faculty_users)} faculty"
                + (f", missing: {', '.join(missing_faculty)}" if missing_faculty else "")
                + ")"
            )
            if missing_faculty:
                unresolved.append((s["title"], missing_faculty))

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Would create/update {len(SEMINARS)} seminars. "
                f"{len(unresolved)} title(s) had unresolved faculty."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"create {created}, update {updated}. "
                f"{len(unresolved)} title(s) had unresolved faculty."
            ))
        if unresolved:
            self.stdout.write("\nUnresolved faculty (attach manually in admin):")
            for title, miss in unresolved:
                self.stdout.write(f"  - {title}: {', '.join(miss)}")
