"""Anonymous donations pathway (task #414): the /payments/ gateway for logged-out
visitors, and the donate-page sign-in nudge."""

from __future__ import annotations

import pytest
from django.urls import reverse

from accounts.models import User


@pytest.mark.django_db
def test_payments_index_anonymous_renders_gateway(client):
    resp = client.get(reverse("payments:index"))
    assert resp.status_code == 200
    templates = {t.name for t in resp.templates}
    assert "payments/gateway.html" in templates
    # It must NOT bounce anonymous users to login.
    assert resp.get("Location") is None


@pytest.mark.django_db
def test_payments_gateway_links_to_login_and_donate(client):
    resp = client.get(reverse("payments:index"))
    body = resp.content.decode()
    assert reverse("donate") in body
    assert reverse("login") in body


@pytest.mark.django_db
def test_payments_index_authenticated_renders_member_page(client):
    user = User.objects.create_user(email="member@example.com", password="pw12345!")
    client.force_login(user)
    resp = client.get(reverse("payments:index"))
    assert resp.status_code == 200
    templates = {t.name for t in resp.templates}
    assert "payments/index.html" in templates


@pytest.mark.django_db
def test_donate_page_shows_signin_nudge_for_anonymous(client):
    resp = client.get(reverse("donate"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "track your donations" in body
    assert reverse("login") in body


@pytest.mark.django_db
def test_donate_page_hides_signin_nudge_for_members(client):
    user = User.objects.create_user(email="m2@example.com", password="pw12345!")
    client.force_login(user)
    resp = client.get(reverse("donate"))
    body = resp.content.decode()
    assert "track your donations" not in body
