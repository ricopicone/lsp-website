"""The /healthz readiness probe used by the blue-green deploy flip."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_healthz_ok(client):
    resp = client.get(reverse("healthz"))
    assert resp.status_code == 200
    assert resp.content == b"ok"


def test_healthz_is_public(client):
    # No auth required — the deploy script curls it before any login is possible.
    assert client.get("/healthz").status_code == 200
