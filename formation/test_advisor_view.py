import pytest
from django.urls import reverse

from accounts.models import User
from formation.models import AdvisorNote


def _advisee_of(advisor):
    """Create a member whose current advisor is ``advisor`` (real advisor API)."""
    from accounts.advisor import set_advisor

    m = User.objects.create_user(email="advisee@x.test")
    set_advisor(m, advisor)
    return m


@pytest.mark.django_db
def test_advisor_sees_advisee_detail(client):
    advisor = User.objects.create_user(email="adv@x.test", password="x")
    advisee = _advisee_of(advisor)
    client.force_login(advisor)
    resp = client.get(
        reverse("formation:advisee_detail", args=[advisee.pk]), SERVER_NAME="localhost"
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_non_advisor_member_gets_403(client):
    advisor = User.objects.create_user(email="adv2@x.test")
    advisee = _advisee_of(advisor)
    stranger = User.objects.create_user(email="s@x.test", password="x")
    client.force_login(stranger)
    resp = client.get(
        reverse("formation:advisee_detail", args=[advisee.pk]), SERVER_NAME="localhost"
    )
    assert resp.status_code in (403, 404)


@pytest.mark.django_db
def test_advisee_cannot_see_notes_about_self(client):
    advisor = User.objects.create_user(email="adv3@x.test")
    advisee = _advisee_of(advisor)
    AdvisorNote.objects.create(advisee=advisee, author=advisor, body="SECRET-NOTE")
    client.force_login(advisee)
    # The advisee's own Formation hub must never contain advisor notes.
    body = client.get("/formation/", SERVER_NAME="localhost").content.decode()
    assert "SECRET-NOTE" not in body
