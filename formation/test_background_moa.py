import pytest
from django.urls import reverse

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _analyst():
    u = User.objects.create_user(email="analyst@example.com", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.formation_background = Profile.FormationBackground.CLINICAL
    u.profile.save()
    u.is_staff = True  # simplest reviewer gate; MoA membership also works
    u.save()
    return u


def _student(email="stu@example.com"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.PRE_CANDIDATE
    u.profile.save()
    return u


def test_queue_denied_to_plain_member(client):
    client.force_login(_student("nobody@example.com"))
    assert client.get(reverse("formation:background_queue")).status_code == 403


def test_queue_lists_in_training_students(client):
    _student("a@example.com")
    client.force_login(_analyst())
    resp = client.get(reverse("formation:background_queue"))
    assert resp.status_code == 200
    assert b"a@example.com" in resp.content


def test_moa_sets_background_with_note(client):
    student = _student()
    client.force_login(_analyst())
    resp = client.post(
        reverse("formation:background_detail", args=[student.pk]),
        {"background": "clinical", "note": "CA-licensed."},
    )
    assert resp.status_code in (302, 303)
    student.profile.refresh_from_db()
    assert student.profile.formation_background == Profile.FormationBackground.CLINICAL
    assert student.background_determinations.first().note == "CA-licensed."


def test_queue_excludes_personas(client):
    persona = _student("persona@example.com")
    persona.profile.is_persona = True
    persona.profile.save()
    real = _student("real@example.com")
    client.force_login(_analyst())
    resp = client.get(reverse("formation:background_queue"))
    assert resp.status_code == 200
    assert b"real@example.com" in resp.content
    assert b"persona@example.com" not in resp.content


def test_landing_unreviewed_count_excludes_personas(client):
    from django.urls import reverse as _reverse

    persona = _student("p2@example.com")
    persona.profile.is_persona = True
    persona.profile.save()
    _student("r2@example.com")  # one real unreviewed student
    client.force_login(_analyst())
    resp = client.get(_reverse("meeting_of_analysts_admin"))
    assert resp.status_code == 200
    assert resp.context["open_backgrounds"] == 1
