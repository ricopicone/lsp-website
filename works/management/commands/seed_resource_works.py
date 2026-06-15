"""Seed the Works catalog with the member publications from the old Wix
``/resources`` page — recent books (with cover images) and member articles.

These are *external* publications: we link out to the publisher / journal
(``url``) and never attach a PDF (we don't hold distribution rights). Each
entry is listed publicly so visitors get a sense of the school's output —
the same books and articles the old site showcased.

Author names are matched against existing Users by first/last name (with a
last-name fallback); unmatched authors are stored in ``external_authors`` so
the work is still attributed. Cover images for the books live alongside this
command in ``data/resource_covers/``.

Idempotent — re-running updates by slug (cover images are only (re)attached
when missing, so admin replacements aren't clobbered).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from works.models import Work, WorkAuthor

User = get_user_model()

COVERS_DIR = Path(__file__).resolve().parent / "data" / "resource_covers"


@dataclass(frozen=True)
class Author:
    first: str
    last: str
    #: Byline to fall back to when no member User matches (e.g. external
    #: co-authors, or members whose stored name differs).
    display: str = ""

    def fallback(self) -> str:
        return self.display or f"{self.first} {self.last}".strip()


@dataclass(frozen=True)
class SeedWork:
    slug: str
    title: str
    year: int
    publication_info: str
    authors: tuple[Author, ...] = field(default_factory=tuple)
    url: str = ""
    abstract: str = ""
    cover: str = ""  # filename within COVERS_DIR


# --- Authors (members appear under "Articles by Members" on the old site) ---

BENNETT = Author("Hannah", "Bennett", "Hannah Bennett")
CARLSON = Author("Shanna", "Carlson de la Torre", "Shanna Carlson de la Torre")
CAVANAGH = Author("Sheila", "Cavanagh")
DAVIDSON = Author("Benjamin", "Davidson")
LOVETT = Author("Matt", "Lovett")
ROGERS = Author("Annie", "Rogers")
SWALES = Author("Stephanie", "Swales")
YOUNG = Author("P.G.", "Young", "P.G. Young")
VANDERWEES = Author("Chris", "Vanderwees")
YU = Author("Yang", "Yu")
FIMIANI = Author("Bret", "Fimiani")

# External (non-member) co-authors / co-editors:
OWENS = Author("Carol", "Owens", "Carol Owens")
HENNESSY = Author("Kristen", "Hennessy", "Kristen Hennessy")


BOOKS: list[SeedWork] = [
    SeedWork(
        slug="psychoanalysis-politics-oppression-resistance",
        title="Psychoanalysis, Politics, Oppression and Resistance: Lacanian Perspectives",
        year=2022,
        publication_info="Edited collection · Routledge, 2022",
        authors=(VANDERWEES, HENNESSY),
        url="https://www.routledge.com/Psychoanalysis-Politics-Oppression-and-Resistance-Lacanian-Perspectives/Vanderwees-Hennessy/p/book/9781032079165",
        abstract=(
            "This innovative text addresses the lack of literature regarding "
            "intersectional approaches to psychoanalysis, underscoring the "
            "importance of thinking through race, class, and gender within "
            "psychoanalytic theory and practice. Bringing together a range of "
            "international contributions, the collection tackles the widespread "
            "perception of psychoanalysis as a discipline detached from the "
            "progressive ideals of social responsibility, institutional "
            "psychotherapy, and community mental health."
        ),
        cover="psychoanalysis-politics-oppression-resistance.jpg",
    ),
    SeedWork(
        slug="psychosis-and-extreme-states",
        title="Psychosis and Extreme States: An Ethic for Treatment",
        year=2021,
        publication_info="The Palgrave Lacan Series · Palgrave Macmillan, 2021",
        authors=(FIMIANI,),
        url="https://link.springer.com/book/10.1007/978-3-030-75440-2",
        abstract=(
            "This book advances a theory of transference-in-psychosis with the "
            "aim of provoking a change in the way the experience of psychosis is "
            "understood and clinically treated. Building on the work of Lacan and "
            "others, it reframes the problem of the 'body' and its relation to "
            "transference and ethics, contending that the aim of the "
            "psychoanalytic experience is the creation of a new ethic for the "
            "treatment."
        ),
        cover="psychosis-extreme-states.jpg",
    ),
    SeedWork(
        slug="incandescent-alphabets",
        title="Incandescent Alphabets: Psychosis and the Enigma of Language",
        year=2016,
        publication_info="Routledge, 2016",
        authors=(ROGERS,),
        url="https://www.routledge.com/Incandescent-Alphabets-Psychosis-and-the-Enigma-of-Language/Rogers/p/book/9781782203476",
        abstract=(
            "This book explores psychosis as knowledge cut off from history, "
            "truth that cannot be articulated in any other form. It gives a "
            "nuanced picture of delusion as a repair of language itself, "
            "following Freud and Lacan in historic and contemporary forms of "
            "psychotic art, writing and speech."
        ),
        cover="incandescent-alphabets.jpg",
    ),
    SeedWork(
        slug="sex-for-structuralists",
        title="Sex for Structuralists: The Non-Oedipal Logics of Femininity and Psychosis",
        year=2018,
        publication_info="The Palgrave Lacan Series · Palgrave Macmillan, 2018",
        authors=(CARLSON,),
        url="https://link.springer.com/book/10.1007/978-3-319-92895-1",
        abstract=(
            "This book examines the structuralisms of Sigmund Freud, Claude "
            "Lévi-Strauss, and Jacques Lacan — and particularly the places of "
            "sexuality, sexual difference, masculinity, and femininity within "
            "them — in order to argue for the radical potential of each. It "
            "contends that structuralism makes itself most useful when it engages "
            "with the non-Oedipal logics of femininity and psychosis."
        ),
        cover="sex-for-structuralists.jpg",
    ),
    SeedWork(
        slug="psychoanalysing-ambivalence-freud-lacan",
        title="Psychoanalysing Ambivalence with Freud and Lacan: On and Off the Couch",
        year=2019,
        publication_info="Routledge, 2019",
        authors=(OWENS, SWALES),
        url="https://www.taylorfrancis.com/books/mono/10.4324/9780429448652/psychoanalysing-ambivalence-freud-lacan-carol-owens-stephanie-swales",
        abstract=(
            "Taking a deep dive into contemporary Western culture, this book "
            "suggests we are all fundamentally ambivalent beings. Drawing on "
            "Freud and Lacan, Carol Owens and Stephanie Swales examine "
            "ambivalence both on and off the analytic couch, tracing its "
            "operation in love, politics, and everyday life."
        ),
        cover="psychoanalysing-ambivalence.jpg",
    ),
    SeedWork(
        slug="perversion-lacanian-approach",
        title="Perversion: A Lacanian Psychoanalytic Approach to the Subject",
        year=2012,
        publication_info="Routledge, 2012",
        authors=(SWALES,),
        url="https://www.routledge.com/Perversion-A-Lacanian-Psychoanalytic-Approach-to-the-Subject/Swales/p/book/9780415501293",
        abstract=(
            "Lacan's psychoanalytic take on what makes a pervert perverse is not "
            "the fact of habitually engaging in specific 'abnormal' or "
            "transgressive sexual acts, but of occupying a particular structural "
            "position in relation to the Other. Perversion is one of Lacan's "
            "three main diagnostic structures, each indicating a fundamentally "
            "different way of solving the problems of alienation, separation, and "
            "castration."
        ),
        cover="perversion-lacanian-approach.jpg",
    ),
]


ARTICLES: list[SeedWork] = [
    # --- Hannah Bennett ---
    SeedWork(
        slug="on-freaking-out-langoisse",
        title="On Freaking Out: L'angoisse",
        year=2020,
        publication_info="European Journal of Psychoanalysis (2020)",
        authors=(BENNETT,),
        url="http://www.journal-psychoanalysis.eu/on-freaking-out-langoisse/",
    ),
    # --- Shanna Carlson de la Torre ---
    SeedWork(
        slug="taking-the-risk-of-a-true-speech",
        title="'Taking the Risk of a True Speech': Transgender and the Lacanian Clinic",
        year=2017,
        publication_info="TSQ: Transgender Studies Quarterly, Vol. 4, Nos. 3–4 (2017), pp. 627–631",
        authors=(CARLSON,),
    ),
    SeedWork(
        slug="the-danish-girls-death-drive",
        title="The Danish Girl's Death Drive",
        year=2017,
        publication_info="TSQ: Transgender Studies Quarterly, Vol. 4, Nos. 3–4 (2017), pp. 675–678",
        authors=(CARLSON,),
    ),
    SeedWork(
        slug="difference-without-limit",
        title="Difference without Limit",
        year=2016,
        publication_info="Powision: Neue Räume für Politik (2016), pp. 44–46",
        authors=(CARLSON,),
    ),
    SeedWork(
        slug="psychoanalytic-a-term-for-a-21st-century-transgender-studies",
        title="'Psychoanalytic': A Term for a 21st Century Transgender Studies",
        year=2014,
        publication_info="TSQ: Transgender Studies Quarterly, Vol. 1, Nos. 1–2 (2014), pp. 169–171",
        authors=(CARLSON,),
    ),
    SeedWork(
        slug="in-defense-of-queer-kinships-oedipus-recast",
        title="In Defense of Queer Kinships: Oedipus Recast",
        year=2010,
        publication_info="Subjectivity, Vol. 3, No. 3 (2010), pp. 263–281",
        authors=(CARLSON,),
    ),
    SeedWork(
        slug="transgender-subjectivity-and-the-logic-of-sexual-difference",
        title="Transgender Subjectivity and the Logic of Sexual Difference",
        year=2010,
        publication_info=(
            "differences: A Journal of Feminist Cultural Studies, "
            "Vol. 21, No. 2 (2010), pp. 46–72"
        ),
        authors=(CARLSON,),
    ),
    # --- Sheila Cavanagh — book chapters ---
    SeedWork(
        slug="tiresias-and-the-other-sexual-difference",
        title="Tiresias and the Other Sexual Difference: Jacques Lacan and Bracha L. Ettinger",
        year=2022,
        publication_info=(
            "In Psychoanalysis, Gender and Sexuality: From Feminism to Trans* · "
            "Cambridge University Press, 2022, pp. 197–211"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="the-controlled-act-of-psychotherapy-in-ontario",
        title="The Controlled Act of Psychotherapy in Ontario: A Lacanian Impasse",
        year=2022,
        publication_info=(
            "In Psychoanalysis, Politics, Oppression & Resistance: Lacanian "
            "Perspectives · Routledge, 2022"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="race-perversion-and-jouissance-in-portrait-of-jason",
        title="Race, Perversion, and Jouissance in Portrait of Jason",
        year=2022,
        publication_info=(
            "In Lacan and Race: Racism, Identity, and Psychoanalytic Theory · "
            "Routledge, 2022, pp. 165–182"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="tiresias-transgression-into-the-feminine",
        title="Tiresias: Bracha L. Ettinger and the Transgression with-in-to the Feminine",
        year=2019,
        publication_info=(
            "In Femininity and Psychoanalysis: Cinema, Culture, Theory · "
            "Routledge, 2019"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="principles-for-psychoanalytic-work-with-trans-clients",
        title="Principles for Psychoanalytic Work with Trans Clients",
        year=2018,
        publication_info=(
            "In International Handbook of Transsexuality and Mental Health · "
            "Routledge, 2018"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="gender-sexuality-and-race-in-the-lacanian-mirror",
        title=(
            "Gender, Sexuality and Race in the Lacanian Mirror: "
            "Urinary Segregation and the Bodily Ego"
        ),
        year=2014,
        publication_info="In Psychoanalytic Geographies · Ashgate, 2014",
        authors=(CAVANAGH,),
    ),
    # --- Sheila Cavanagh — edited special issues ---
    SeedWork(
        slug="the-psychoanalysis-of-bracha-l-ettinger",
        title="The Psychoanalysis of Bracha L. Ettinger (edited special issue)",
        year=2022,
        publication_info=(
            "Psychoanalysis, Culture and Society, Vol. 27 (2022) — special issue, editor"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="transgender-and-psychoanalysis-special-issue",
        title="Transgender and Psychoanalysis (edited special double issue)",
        year=2017,
        publication_info=(
            "TSQ: Transgender Studies Quarterly, Vol. 4, No. 4 (2017) "
            "— special double issue, editor"
        ),
        authors=(CAVANAGH,),
    ),
    # --- Sheila Cavanagh — peer-reviewed journal articles ---
    SeedWork(
        slug="the-matrixial-gaze-transgender-in-boys-dont-cry",
        title="The Matrixial Gaze: Transgender in Boys Don't Cry",
        year=2022,
        publication_info="Studies in Gender and Sexuality, 23.4 (2022), pp. 243–255",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="transgender-and-the-other-sexual-difference-in-trisha",
        title="Transgender and the Other Sexual Difference in Vivek Shraya's Trisha",
        year=2022,
        publication_info="Psychoanalysis, Culture & Society, Vol. 27 (2022), pp. 485–501",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="sociotherapy-in-the-time-of-covid-19",
        title=(
            "Sociotherapy in the Time of COVID-19: A Critical Position Paper on "
            "the Importance of Sociology in Psychotherapy"
        ),
        year=2021,
        publication_info="Journal of Applied Social Sciences, Vol. 15(2) (2021), pp. 211–225",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="queer-theory-psychoanalysis-and-the-symptom",
        title="Queer Theory, Psychoanalysis and the Symptom: A Lacanian Approach",
        year=2019,
        publication_info="Studies in Gender and Sexuality, 20(4) (2019), pp. 226–230",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="transgender-hysteria-and-the-other-sexual-difference",
        title="Transgender, Hysteria, and the Other Sexual Difference: An Ettingerian Approach",
        year=2019,
        publication_info="Studies in Gender and Sexuality, 20(1) (2019), pp. 36–50",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="transgender-embodiment-a-lacanian-approach",
        title="Transgender Embodiment: A Lacanian Approach",
        year=2018,
        publication_info="The Psychoanalytic Review, 105(3) (2018), pp. 303–327",
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="bracha-l-ettinger-jacques-lacan-and-tiresias",
        title="Bracha L. Ettinger, Jacques Lacan and Tiresias: The Other Sexual Difference",
        year=2018,
        publication_info=(
            "Sitegeist: A Journal for Psychoanalysis and Philosophy, "
            "Issue 13 (2018), pp. 32–50"
        ),
        authors=(CAVANAGH,),
    ),
    SeedWork(
        slug="antigones-legacy",
        title="Antigone's Legacy: A Feminist Psychoanalytic of an Other Sexual Difference",
        year=2017,
        publication_info="MAMSIE: Studies in the Maternal, 9(1) (2017)",
        authors=(CAVANAGH,),
        url="http://doi.org/10.16995/sim.223",
    ),
    # --- Benjamin Davidson ---
    SeedWork(
        slug="revolt-act-i",
        title="Revolt! Act I",
        year=2019,
        publication_info="European Journal of Psychoanalysis, No. 12 — 2019/2",
        authors=(DAVIDSON,),
        url="http://www.journal-psychoanalysis.eu/?s=Davidson",
    ),
    SeedWork(
        slug="revolt-act-ii",
        title="Revolt! Act II",
        year=2019,
        publication_info="European Journal of Psychoanalysis, No. 12 — 2019/2",
        authors=(DAVIDSON,),
        url="http://www.journal-psychoanalysis.eu/revolt-part-2/",
    ),
    # --- Matt Lovett ---
    SeedWork(
        slug="lacanian-anxieties-trans-surgeries",
        title=(
            "Lacanian Anxieties: Trans Surgeries, Countertransference, "
            "and the Fantasy of the Whole"
        ),
        year=2024,
        publication_info="TSQ: Transgender Studies Quarterly, Vol. 11, No. 3 (2024), pp. 441–458",
        authors=(LOVETT,),
        url="https://read.dukeupress.edu/tsq/article-abstract/11/3/458/391172/Lacanian-AnxietiesTrans-Surgeries",
    ),
    SeedWork(
        slug="the-sexual-genesis-of-thought",
        title="The Sexual Genesis of Thought",
        year=2024,
        publication_info=(
            "Penumbr(a): A Journal of Psychoanalysis and Modernity, "
            "No. 3, After Anti-Oedipus (2024), pp. 25–53"
        ),
        authors=(LOVETT,),
        url="https://www.penumbrajournal.org/no-no-3-/-after-anti-oedipus",
    ),
    # --- Annie Rogers ---
    SeedWork(
        slug="review-the-writing-cure",
        title="Review of The Writing Cure (E. Lieber)",
        year=2022,
        publication_info="Psychoanalysis, Culture and Society, November 10, 2022 — book review",
        authors=(ROGERS,),
        url="https://rdcu.be/cZq66",
    ),
    SeedWork(
        slug="becoming-an-analyst-apres-coup",
        title="Becoming an Analyst: Après-coup",
        year=2020,
        publication_info="Psychoanalytic Inquiry, 40:2 (2020), pp. 90–99",
        authors=(ROGERS,),
        url="https://doi.org/10.1080/07351690.2020.1702438",
    ),
    SeedWork(
        slug="the-father-of-the-name",
        title="The Father of the Name: A Child's Analysis Through the Last Teachings of Lacan",
        year=2017,
        publication_info=(
            "In Lacanian Psychoanalysis with Babies, Children and Adolescents · "
            "Karnac Books, 2017"
        ),
        authors=(ROGERS,),
    ),
    # --- Stephanie Swales ---
    SeedWork(
        slug="why-the-zombies-ate-my-neighbors",
        title="Why the Zombies Ate My Neighbors: Whither Ambivalence?",
        year=2018,
        publication_info=(
            "In On Psychoanalysis and Violence: Contemporary Lacanian "
            "Perspectives · Routledge, 2018"
        ),
        authors=(SWALES,),
    ),
    SeedWork(
        slug="session-iv-the-psychology-of-the-rich-pausanias",
        title="Session IV: The Psychology of the Rich: Pausanias",
        year=2020,
        publication_info=(
            "In Reading Lacan's Seminar VIII: On Transference · "
            "Palgrave Macmillan, 2020"
        ),
        authors=(SWALES,),
    ),
    SeedWork(
        slug="session-xviii-real-presence",
        title="Session XVIII: Real Presence",
        year=2020,
        publication_info=(
            "In Reading Lacan's Seminar VIII: On Transference · "
            "Palgrave Macmillan, 2020"
        ),
        authors=(SWALES,),
    ),
    SeedWork(
        slug="metaphor-of-the-subject",
        title="Metaphor of the Subject",
        year=2018,
        publication_info=(
            "In Reading Lacan's Écrits: From 'Signification of the Phallus' to "
            "'Metaphor of the Subject' · Routledge, 2018"
        ),
        authors=(SWALES,),
    ),
    SeedWork(
        slug="the-phobic-and-fetish-objects",
        title="The Phobic and Fetish Objects",
        year=2018,
        publication_info=(
            "In Studying Lacan's Seminars IV and V: From Lack to Desire · "
            "Routledge, 2018"
        ),
        authors=(SWALES,),
    ),
    # --- P.G. Young ---
    SeedWork(
        slug="lacan-reading-freud-seminar-v",
        title=(
            "Lacan Reading Freud: On the Relationship of Seminar V to Jokes and "
            "Their Relationship to the Unconscious"
        ),
        year=2019,
        publication_info=(
            "In Studying Lacan's Seminars IV and V: From Lack to Desire · "
            "Routledge, 2019"
        ),
        authors=(YOUNG,),
    ),
    # --- Chris Vanderwees ---
    SeedWork(
        slug="dreams-of-destruction",
        title="Dreams of Destruction",
        year=2018,
        publication_info="Museum of Dreams, ed. Sharon Sliwinski (2018)",
        authors=(VANDERWEES,),
        url="https://www.museumofdreams.org/dreams-of-destruction",
    ),
    SeedWork(
        slug="erich-fromms-psychoanalysis-of-transcendence",
        title=(
            "Erich Fromm's Psychoanalysis of Transcendence and the Photography "
            "of Detroit's Ruins"
        ),
        year=2017,
        publication_info=(
            "In Progressive Psychoanalysis: Essays on Psychoanalysis as a Social "
            "Justice Movement · Cambridge Scholars Publishing, 2017, pp. 42–66"
        ),
        authors=(VANDERWEES,),
    ),
    # --- Yang Yu ---
    SeedWork(
        slug="the-birth-of-the-colonial-subject",
        title=(
            "The Birth of the Colonial Subject — A Lacanian Reading of 'Shooting "
            "an Elephant' and Other Burmese Texts"
        ),
        year=2018,
        publication_info="Foreign Literatures (《国外文学》, CSSCI), 150(2) (2018), pp. 109–117",
        authors=(YU,),
    ),
]


def _resolve_user(author: Author):
    """Case-insensitive first+last lookup, with a last-name fallback.

    Returns a User or None. The fallback (first + final word of the surname)
    catches members whose stored surname differs from the byline spelling
    (e.g. a particle-laden compound surname), while staying specific enough
    to avoid false positives within an ~80-member roster.
    """
    exact = User.objects.filter(
        first_name__iexact=author.first, last_name__iexact=author.last,
    )
    if exact.count() == 1:
        return exact.first()
    surname_tail = author.last.split()[-1] if author.last else author.last
    if surname_tail and surname_tail.lower() != author.last.lower():
        loose = User.objects.filter(
            first_name__iexact=author.first, last_name__iexact=surname_tail,
        )
        if loose.count() == 1:
            return loose.first()
    return None


class Command(BaseCommand):
    help = (
        "Seed the Works catalog with member books + articles from the old Wix "
        "/resources page. Idempotent — updates by slug."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created/updated without writing anything.",
        )
        parser.add_argument(
            "--books-only",
            action="store_true",
            help="Seed only the books (skip the article entries).",
        )

    def handle(self, *args, dry_run: bool, books_only: bool, **opts):
        entries = list(BOOKS) if books_only else list(BOOKS) + list(ARTICLES)
        created = updated = 0
        unmatched: list[tuple[str, str]] = []
        missing_covers: list[str] = []

        for entry in entries:
            users: list = []
            externals: list[str] = []
            for author in entry.authors:
                u = _resolve_user(author)
                if u is None:
                    externals.append(author.fallback())
                    unmatched.append((entry.slug, author.fallback()))
                else:
                    users.append(u)

            existing = Work.objects.filter(slug=entry.slug).first()
            action = "update" if existing else "create"

            cover_path = COVERS_DIR / entry.cover if entry.cover else None
            if cover_path and not cover_path.is_file():
                missing_covers.append(entry.cover)
                cover_path = None

            if dry_run:
                byline = "; ".join(
                    f"{u.first_name} {u.last_name}" for u in users
                ) or "(no matched members)"
                if externals:
                    byline += f"  + external: {', '.join(externals)}"
                self.stdout.write(f"  {action}: {entry.slug}  [{byline}]")
                created += action == "create"
                updated += action == "update"
                continue

            with transaction.atomic():
                w = existing or Work(slug=entry.slug)
                w.title = entry.title
                w.kind = Work.Kind.EXTERNAL
                w.abstract = entry.abstract
                w.publication_info = entry.publication_info
                w.publication_date = date(entry.year, 1, 1)
                w.url = entry.url
                w.listing_visibility = Work.Visibility.PUBLIC
                w.content_visibility = Work.Visibility.MEMBERS
                w.external_authors = "; ".join(externals)
                # Attach the cover only if the work doesn't already have one,
                # so an admin's replacement survives a re-run.
                if cover_path and not w.cover_image:
                    with cover_path.open("rb") as fh:
                        w.cover_image.save(cover_path.name, File(fh), save=False)
                w.save()
                WorkAuthor.objects.filter(work=w).delete()
                for i, user in enumerate(users):
                    WorkAuthor.objects.create(work=w, user=user, display_order=i)

                if existing:
                    updated += 1
                    self.stdout.write(f"  updated: {entry.slug}")
                else:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  created: {entry.slug}"))

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(f"{prefix}{created} created, {updated} updated.")
        if missing_covers:
            self.stdout.write(self.style.WARNING("Missing cover files:"))
            for name in sorted(set(missing_covers)):
                self.stdout.write(f"  - {name}")
        if unmatched:
            self.stdout.write(self.style.WARNING(
                "Authors stored as external (no member match):"
            ))
            for slug, name in unmatched:
                self.stdout.write(f"  - {slug}: {name}")
