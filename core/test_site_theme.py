"""Tests for the site-theme skin (wix/Classic default vs opt-out modern)."""
from types import SimpleNamespace

import pytest
from django.urls import reverse

from core.context_processors import SITE_THEME_COOKIE, site_theme


def test_default_is_wix():
    request = SimpleNamespace(COOKIES={})
    assert site_theme(request) == {"site_theme": "wix"}


def test_cookie_selects_modern():
    request = SimpleNamespace(COOKIES={SITE_THEME_COOKIE: "modern"})
    assert site_theme(request) == {"site_theme": "modern"}


def test_invalid_cookie_falls_back_to_default():
    request = SimpleNamespace(COOKIES={SITE_THEME_COOKIE: "bogus"})
    assert site_theme(request) == {"site_theme": "wix"}


@pytest.mark.django_db
def test_set_site_theme_sets_cookie_and_redirects(client):
    url = reverse("core:set_site_theme", args=["wix"])
    resp = client.get(url + "?next=/about/", SERVER_NAME="localhost")
    assert resp.status_code == 302
    assert resp.url == "/about/"
    assert resp.cookies[SITE_THEME_COOKIE].value == "wix"


@pytest.mark.django_db
def test_set_site_theme_rejects_offsite_next(client):
    url = reverse("core:set_site_theme", args=["modern"])
    resp = client.get(url + "?next=https://evil.example/x", SERVER_NAME="localhost")
    assert resp.status_code == 302
    assert resp.url == "/"


@pytest.mark.django_db
def test_set_site_theme_normalizes_unknown_theme(client):
    url = reverse("core:set_site_theme", args=["nope"])
    resp = client.get(url, SERVER_NAME="localhost")
    assert resp.cookies[SITE_THEME_COOKIE].value == "wix"
