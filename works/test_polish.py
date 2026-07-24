"""Tests for the Works polish (task #465): structured citation fields,
form handling, detail-page presentation, sort options, grid/list toggle,
and the backfill_citations command."""

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
