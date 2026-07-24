"""Tests for the Works polish (task #465): structured citation fields,
form handling, detail-page presentation, sort options, grid/list toggle,
and the backfill_citations command."""

import datetime
import json

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


class TestIndexSort:
    @pytest.fixture(autouse=True)
    def works(self, author, django_user_model):
        z = django_user_model.objects.create_user(
            email="z@example.org", password="x", first_name="Ann", last_name="Zed",
        )
        self.a = make_work(title="Alpha", slug="alpha", author=z,
                           publication_date=datetime.date(2020, 1, 1))
        self.b = make_work(title="Beta", slug="beta",
                           publication_date=datetime.date(2024, 1, 1), author=author)
        self.c = make_work(title="Gamma", slug="gamma")  # undated, no authors

    def _titles(self, client, sort):
        r = client.get("/works/", {"sort": sort})
        return [w.title for w in r.context["works"]]

    def test_year_newest_first_undated_last(self, client):
        assert self._titles(client, "year") == ["Beta", "Alpha", "Gamma"]

    def test_added_recent_first(self, client):
        assert self._titles(client, "added") == ["Gamma", "Beta", "Alpha"]

    def test_author_alpha_blank_last(self, client):
        # Swales < Zed; the author-less work sorts last.
        assert self._titles(client, "author") == ["Beta", "Alpha", "Gamma"]

    def test_default_and_bogus_return_all_as_random(self, client):
        for params in ({}, {"sort": "random"}, {"sort": "nonsense"}):
            r = client.get("/works/", params)
            assert {w.title for w in r.context["works"]} == {"Alpha", "Beta", "Gamma"}
            assert r.context["selected_sort"] == "random"


class TestViewToggle:
    def test_default_grid(self, client):
        make_work()
        r = client.get("/works/")
        assert r.context["view_mode"] == "grid"

    def test_explicit_list_sets_cookie(self, client):
        make_work()
        r = client.get("/works/", {"view": "list"})
        assert r.context["view_mode"] == "list"
        assert r.cookies["works_view"].value == "list"

    def test_cookie_remembered(self, client):
        make_work()
        client.cookies["works_view"] = "list"
        r = client.get("/works/")
        assert r.context["view_mode"] == "list"
        assert "works_view" not in r.cookies  # not re-set on read

    def test_query_beats_cookie_and_bogus_falls_back(self, client):
        make_work()
        client.cookies["works_view"] = "list"
        assert client.get("/works/", {"view": "grid"}).context["view_mode"] == "grid"
        # The explicit request above also updated the cookie; re-seed it to
        # check that a bogus ?view= falls back to the cookie.
        client.cookies["works_view"] = "list"
        assert client.get("/works/", {"view": "x"}).context["view_mode"] == "list"


class TestBackfillCitations:
    def test_fills_only_empty_and_dry_run(self, tmp_path):
        from django.core.management import call_command

        w = make_work(title="Fill Me", slug="fill-me", container_title="Kept")
        mapping = [{"slug": "fill-me", "fields": {
            "container_title": "Overwritten?", "publisher": "Routledge",
        }}]
        p = tmp_path / "m.json"
        p.write_text(json.dumps(mapping))

        call_command("backfill_citations", str(p), "--dry-run")
        w.refresh_from_db()
        assert w.publisher == ""            # dry run wrote nothing

        call_command("backfill_citations", str(p))
        w.refresh_from_db()
        assert w.publisher == "Routledge"   # empty field filled
        assert w.container_title == "Kept"  # member data never overwritten

    def test_unknown_slug_and_field_rejected(self, tmp_path):
        from django.core.management import CommandError, call_command

        p = tmp_path / "m.json"
        p.write_text(json.dumps([{"slug": "nope", "fields": {"publisher": "X"}}]))
        with pytest.raises(CommandError):
            call_command("backfill_citations", str(p))

        make_work(title="Fill Me", slug="fill-me")
        p.write_text(json.dumps([{"slug": "fill-me", "fields": {"title": "hack"}}]))
        with pytest.raises(CommandError):
            call_command("backfill_citations", str(p))
