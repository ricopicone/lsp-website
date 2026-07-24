"""Tests for the Works polish (task #465): structured citation fields,
form handling, detail-page presentation, sort options, grid/list toggle,
and the backfill_citations command."""

import datetime

import pytest

from works.models import Work, WorkAuthor

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        email="s@example.org", password="x", first_name="Stephanie", last_name="Swales",
    )


def make_work(author=None, **kw):
    kw.setdefault("title", "On the Gaze")
    kw.setdefault("slug", kw["title"].lower().replace(" ", "-"))
    kw.setdefault("kind", Work.Kind.EXTERNAL)
    w = Work.objects.create(**kw)
    if author:
        WorkAuthor.objects.create(work=w, user=author, display_order=0)
    return w


class TestStructuredCitationFields:
    def test_fields_default_blank_and_flag_off(self):
        w = make_work()
        assert w.external_type == ""
        assert w.has_structured_citation is False

    def test_flag_on_when_any_field_set(self):
        w = make_work(container_title="Psychoanalytic Review")
        assert w.has_structured_citation is True

    def test_doi_url(self):
        w = make_work(doi="10.1234/xyz")
        assert w.doi_url == "https://doi.org/10.1234/xyz"
        assert make_work(title="No doi", slug="no-doi").doi_url == ""


class TestWorkFormCitation:
    def _data(self, **kw):
        base = {
            "title": "T", "kind": "external",
            "listing_visibility": "public", "content_visibility": "members",
            "external_type": "article", "container_title": "J of X",
            "volume": "1", "issue": "2", "pages": "3–4",
            "doi": "https://doi.org/10.1234/xyz",
        }
        base.update(kw)
        return base

    def test_saves_structured_fields_and_normalizes_doi(self, author):
        from works.forms import WorkForm

        form = WorkForm(self._data(), current_user=author)
        assert form.is_valid(), form.errors
        w = form.save()
        assert w.container_title == "J of X"
        assert w.doi == "10.1234/xyz"

    def test_doi_prefix_variants(self, author):
        from works.forms import WorkForm

        for raw in ("doi:10.1/a", "http://dx.doi.org/10.1/a", "10.1/a"):
            form = WorkForm(self._data(doi=raw), current_user=author)
            assert form.is_valid(), form.errors
            assert form.cleaned_data["doi"] == "10.1/a"


class TestDetailCitation:
    def test_source_line_and_cite_block(self, client):
        w = make_work(
            external_type=Work.ExternalType.ARTICLE,
            container_title="Psychoanalytic Review", volume="12", pages="33–58",
            publication_date=datetime.date(2024, 5, 1),
            publication_info="Special issue on the gaze",
        )
        r = client.get(w.get_absolute_url())
        html = r.content.decode()
        assert "<i>Psychoanalytic Review</i>" in html
        assert "Special issue on the gaze" in html   # note AND structured line
        assert "2024" in html                        # date no longer suppressed
        assert "Cite" in html
        assert 'id="copy-citation"' in html

    def test_date_shows_alongside_legacy_info(self, client):
        w = make_work(
            title="Legacy", slug="legacy",
            publication_info="Journal of X, Vol 12 (2024)",
            publication_date=datetime.date(2024, 5, 1),
        )
        html = client.get(w.get_absolute_url()).content.decode()
        assert "Journal of X, Vol 12 (2024)" in html
        assert "May 1, 2024" in html

    def test_external_link_label(self, client):
        w = make_work(title="Linked", slug="linked", url="https://ex.org/p")
        r = client.get(w.get_absolute_url())
        assert "View at publisher" in r.content.decode()
        w2 = make_work(title="Palimp", slug="palimp", kind=Work.Kind.PALIMPSEST,
                       url="https://ex.org/q")
        r2 = client.get(w2.get_absolute_url())
        assert "External link" in r2.content.decode()
