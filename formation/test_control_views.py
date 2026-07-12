import datetime as dt

import pytest
from django.urls import reverse

from accounts.models import User
from formation.models import ControlAnalysis


@pytest.mark.django_db
def test_member_adds_control_entry(client):
    u = User.objects.create_user(email="c@x.test", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:control_add"), {
        "supervisor_name": "Dr A", "modality": "remote", "requirement": "four_year",
        "start_date": "2021-01-01", "end_date": "", "notes": "",
    }, SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    assert ControlAnalysis.objects.filter(member=u, supervisor_name="Dr A").exists()


@pytest.mark.django_db
def test_member_cannot_edit_others_entry(client):
    owner = User.objects.create_user(email="o@x.test")
    other = User.objects.create_user(email="x@x.test", password="x")
    ca = ControlAnalysis.objects.create(member=owner, supervisor_name="S",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(other)
    resp = client.post(reverse("formation:control_edit", args=[ca.pk]),
        {"supervisor_name": "H", "modality": "remote", "start_date": "2021-01-01"},
        SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)
    ca.refresh_from_db()
    assert ca.supervisor_name == "S"


@pytest.mark.django_db
def test_member_edits_own_entry(client):
    u = User.objects.create_user(email="e@x.test", password="x")
    ca = ControlAnalysis.objects.create(member=u, supervisor_name="Old",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(u)
    resp = client.post(reverse("formation:control_edit", args=[ca.pk]), {
        "supervisor_name": "New", "modality": "in_person", "requirement": "two_year",
        "start_date": "2021-01-01", "end_date": "", "notes": "",
    }, SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    ca.refresh_from_db()
    assert ca.supervisor_name == "New"
    assert ca.modality == "in_person"


@pytest.mark.django_db
def test_member_deletes_own_entry(client):
    u = User.objects.create_user(email="d@x.test", password="x")
    ca = ControlAnalysis.objects.create(member=u, supervisor_name="ToDelete",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(u)
    resp = client.post(reverse("formation:control_delete", args=[ca.pk]),
        SERVER_NAME="localhost")
    assert resp.status_code in (302, 303)
    assert not ControlAnalysis.objects.filter(pk=ca.pk).exists()


@pytest.mark.django_db
def test_member_cannot_delete_others_entry(client):
    owner = User.objects.create_user(email="o2@x.test")
    other = User.objects.create_user(email="x2@x.test", password="x")
    ca = ControlAnalysis.objects.create(member=owner, supervisor_name="S",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(other)
    resp = client.post(reverse("formation:control_delete", args=[ca.pk]),
        SERVER_NAME="localhost")
    assert resp.status_code in (403, 404)
    assert ControlAnalysis.objects.filter(pk=ca.pk).exists()


@pytest.mark.django_db
def test_formation_tab_shows_control_context(client):
    u = User.objects.create_user(email="f@x.test", password="x")
    ControlAnalysis.objects.create(member=u, supervisor_name="S",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(u)
    resp = client.get(reverse("formation:formation"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert "control_entries" in resp.context
    assert "control_progress" in resp.context
    assert resp.context["control_progress"]["total_target"] in (6, 8)
