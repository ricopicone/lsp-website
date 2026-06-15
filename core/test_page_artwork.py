"""Tests for the section-landing artwork resolver + context processor.

The hero machinery must (a) resolve a mapped view name to its Artwork, (b)
return None for unmapped/empty view names, and (c) survive a request with no
resolver_match (e.g. some error responses) without raising.
"""
from types import SimpleNamespace

from core import page_artwork
from core.context_processors import page_artwork as page_artwork_cp


def test_for_view_returns_none_when_unmapped():
    assert page_artwork.for_view("definitely-not-a-real-view") is None
    assert page_artwork.for_view(None) is None
    assert page_artwork.for_view("") is None


def test_for_view_resolves_a_mapped_entry(monkeypatch):
    art = page_artwork.Artwork(image="img/artwork/x.webp", artist="A", title="T")
    monkeypatch.setattr(page_artwork, "PAGE_ARTWORK", {"some_view": art})
    assert page_artwork.for_view("some_view") is art


def test_context_processor_handles_missing_resolver_match():
    request = SimpleNamespace(resolver_match=None)
    assert page_artwork_cp(request) == {"page_artwork": None}


def test_context_processor_resolves_view_name(monkeypatch):
    art = page_artwork.Artwork(image="img/artwork/y.webp")
    monkeypatch.setattr(page_artwork, "PAGE_ARTWORK", {"about": art})
    request = SimpleNamespace(resolver_match=SimpleNamespace(view_name="about"))
    assert page_artwork_cp(request) == {"page_artwork": art}
