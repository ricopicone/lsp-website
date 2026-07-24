"""Unit tests for the Chicago author-date citation renderer (task #465)."""

import datetime

import pytest

from works.citation import citation_html, citation_text, source_html
from works.models import Work, WorkAuthor

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        email="s@example.org", password="x", first_name="Stephanie", last_name="Swales",
    )


def make_work(author=None, **kw):
    kw.setdefault("title", "Surplus Enjoyment")
    kw.setdefault("slug", kw["title"].lower().replace(" ", "-"))
    kw.setdefault("kind", Work.Kind.EXTERNAL)
    w = Work.objects.create(**kw)
    if author:
        WorkAuthor.objects.create(work=w, user=author, display_order=0)
    return w


def test_article(author):
    w = make_work(
        author=author,
        external_type=Work.ExternalType.ARTICLE,
        container_title="Psychoanalytic Review",
        volume="12", issue="2", pages="33–58",
        publication_date=datetime.date(2024, 5, 1),
        doi="10.1234/xyz",
    )
    text = citation_text(w)
    assert text == (
        "Swales, Stephanie. 2024. “Surplus Enjoyment.” "
        "Psychoanalytic Review 12 (2): 33–58. https://doi.org/10.1234/xyz."
    )
    html = citation_html(w)
    assert "<i>Psychoanalytic Review</i>" in html
    assert 'href="https://doi.org/10.1234/xyz"' in html


def test_book(author):
    w = make_work(
        author=author, title="Book of Drives", slug="bod",
        external_type=Work.ExternalType.BOOK, publisher="Routledge",
        edition="2nd ed.", publication_date=datetime.date(2023, 1, 1),
    )
    assert citation_text(w) == "Swales, Stephanie. 2023. Book of Drives. 2nd ed. Routledge."
    assert "<i>Book of Drives</i>" in citation_html(w)


def test_chapter(author):
    w = make_work(
        author=author, title="On Lack", slug="on-lack",
        external_type=Work.ExternalType.CHAPTER,
        container_title="Reading Lacan", editors="Derek Hook", pages="101–120",
        publisher="Palgrave", publication_date=datetime.date(2022, 1, 1),
    )
    assert citation_text(w) == (
        "Swales, Stephanie. 2022. “On Lack.” In Reading Lacan, "
        "edited by Derek Hook, 101–120. Palgrave."
    )


def test_edited_volume_marks_eds(author):
    w = make_work(
        author=author, title="Lacan Reader", slug="lr",
        external_type=Work.ExternalType.EDITED_VOLUME, publisher="Routledge",
        publication_date=datetime.date(2021, 1, 1),
    )
    assert citation_text(w).startswith("Swales, Stephanie, ed. 2021.")


def test_two_authors_and_external(author, django_user_model):
    other = django_user_model.objects.create_user(
        email="d@example.org", password="x", first_name="Derek", last_name="Hook",
    )
    w = make_work(author=author, external_authors="Jane Doe")
    WorkAuthor.objects.create(work=w, user=other, display_order=1)
    assert citation_text(w).startswith("Swales, Stephanie, Derek Hook, and Jane Doe.")


def test_no_date_renders_nd(author):
    w = make_work(author=author)
    assert " n.d. " in " " + citation_text(w) + " "


def test_escaping():
    w = make_work(title="A <script> Title", container_title="J<b>X")
    html = citation_html(w)
    assert "<script>" not in html
    assert "<b>" not in html.replace("<i>", "").replace("</i>", "")


def test_source_html_omits_authors_and_title(author):
    w = make_work(
        author=author, external_type=Work.ExternalType.ARTICLE,
        container_title="Psychoanalytic Review", volume="12", pages="33–58",
        publication_date=datetime.date(2024, 5, 1),
    )
    s = source_html(w)
    assert "Swales" not in s and "Surplus" not in s
    assert "<i>Psychoanalytic Review</i>" in s


def test_source_html_empty_without_data():
    assert source_html(make_work(title="Bare", slug="bare")) == ""
