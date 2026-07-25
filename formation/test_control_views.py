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
    from accounts.models import Profile

    u = User.objects.create_user(email="f@x.test", password="x")
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    u.profile.save()
    ControlAnalysis.objects.create(member=u, supervisor_name="S",
        modality="remote", start_date=dt.date(2021, 1, 1))
    client.force_login(u)
    resp = client.get(reverse("formation:formation"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert "control_entries" in resp.context
    assert "control_progress" in resp.context
    assert resp.context["control_progress"]["total_target"] in (6, 8)


def test_control_form_school_dropdown_lists_only_active_public_analysts(db):
    from accounts.models import Profile, User
    from formation.forms import ControlAnalysisForm

    member = User.objects.create_user(email="mem@example.com", password="x")
    analyst = User.objects.create_user(email="an@example.com", password="x")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.public = True
    analyst.profile.save()
    hidden = User.objects.create_user(email="hid@example.com", password="x")
    hidden.profile.role = Profile.Role.ANALYST
    hidden.profile.public = False
    hidden.profile.save()

    form = ControlAnalysisForm(user=member)
    qs = form.fields["school_analyst"].queryset
    assert analyst in qs and hidden not in qs and member not in qs


def test_control_form_school_dropdown_excludes_personas(db):
    """Training-sandbox persona analysts must never appear as selectable
    control-analysis supervisors (personas-off-public-rosters convention)."""
    from accounts.models import Profile, User
    from formation.forms import ControlAnalysisForm

    member = User.objects.create_user(email="mem3@example.com", password="x")
    analyst = User.objects.create_user(email="an3@example.com", password="x")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.public = True
    analyst.profile.save()
    persona = User.objects.create_user(email="persona3@example.com", password="x")
    persona.profile.role = Profile.Role.ANALYST
    persona.profile.public = True
    persona.profile.is_persona = True
    persona.profile.save()

    form = ControlAnalysisForm(user=member)
    qs = form.fields["school_analyst"].queryset
    assert analyst in qs and persona not in qs


def test_control_form_school_dropdown_labels_are_names_not_emails(db):
    """The analyst dropdown shows names, not User.__str__ (the email)."""
    from accounts.models import Profile, User
    from formation.forms import ControlAnalysisForm

    member = User.objects.create_user(email="mem4@example.com", password="x")
    named = User.objects.create_user(
        email="jane@example.com", password="x", first_name="Jane", last_name="Roe")
    named.profile.role = Profile.Role.ANALYST
    named.profile.public = True
    named.profile.save()
    nameless = User.objects.create_user(email="noname@example.com", password="x")
    nameless.profile.role = Profile.Role.ANALYST
    nameless.profile.public = True
    nameless.profile.save()

    label_for = ControlAnalysisForm(user=member).fields["school_analyst"].label_from_instance
    assert label_for(named) == "Jane Roe"
    # Falls back to the email only when there is no name.
    assert label_for(nameless) == "noname@example.com"


def test_control_save_syncs_supervisor_name_from_school_analyst(client, db):
    from django.urls import reverse

    from accounts.models import Profile, User
    from formation.models import ControlAnalysis

    member = User.objects.create_user(email="mem2@example.com", password="x")
    analyst = User.objects.create_user(
        email="an2@example.com", password="x", first_name="Jane", last_name="Roe")
    analyst.profile.role = Profile.Role.ANALYST
    analyst.profile.public = True
    analyst.profile.save()
    client.force_login(member)

    resp = client.post(reverse("formation:control_add"), {
        "supervisor_name": "", "school_analyst": analyst.pk,
        "requirement": "four_year", "modality": "remote",
        "start_date": "2020-01-01",
    })
    assert resp.status_code == 302
    ca = ControlAnalysis.objects.get(member=member)
    assert ca.school_analyst_id == analyst.pk
    assert ca.supervisor_name == "Jane Roe"


@pytest.mark.django_db
def test_formation_tab_shows_neutral_when_unreviewed(client):
    from accounts.models import Profile

    u = User.objects.create_user(email="stu@example.com", password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.formation_background = Profile.FormationBackground.UNREVIEWED
    u.profile.save()
    client.force_login(u)

    resp = client.get(reverse("formation:formation"), SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert b"Meeting of Analysts" in resp.content  # neutral copy
    assert b"total years across your control analyses" not in resp.content
