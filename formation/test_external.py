import pytest
from django.urls import reverse

from accounts.models import User
from formation.models import ExternalActivity


@pytest.mark.django_db
def test_member_adds_external_activity(client):
    u = User.objects.create_user(email="e@x.test", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:external_add"), {
        "kind": "course_taught", "title": "Reading Seminar XI",
        "venue": "CIIS", "start_date": "2025-09-01", "end_date": "",
        "url": "", "notes": "",
    }, SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    assert ExternalActivity.objects.filter(member=u, title="Reading Seminar XI").exists()


@pytest.mark.django_db
def test_member_cannot_delete_others_activity(client):
    owner = User.objects.create_user(email="o2@x.test")
    other = User.objects.create_user(email="x2@x.test", password="x")
    a = ExternalActivity.objects.create(member=owner, kind="publication",
        title="T", start_date="2024-01-01")
    client.force_login(other)
    resp = client.post(reverse("formation:external_delete", args=[a.pk]), SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)
    assert ExternalActivity.objects.filter(pk=a.pk).exists()
