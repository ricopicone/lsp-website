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
