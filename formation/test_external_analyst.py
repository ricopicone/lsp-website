import pytest

from accounts.models import User
from formation.models import ExternalControlAnalyst

pytestmark = pytest.mark.django_db


def test_external_request_defaults_to_requested():
    u = User.objects.create_user(email="m@example.com", password="x")
    e = ExternalControlAnalyst.objects.create(
        member=u, name="Dr External", description="Longtime supervisor.",
    )
    assert e.status == ExternalControlAnalyst.Status.REQUESTED
    assert e.is_open is True


def test_member_requests_external_analyst(client):
    from django.urls import reverse
    u = User.objects.create_user(email="req@example.com", password="x")
    client.force_login(u)
    resp = client.post(reverse("formation:external_analyst_request"), {
        "name": "Dr Outside", "email": "dr@out.example",
        "description": "My supervisor of ten years.",
    })
    assert resp.status_code == 302
    e = ExternalControlAnalyst.objects.get(member=u)
    assert e.status == ExternalControlAnalyst.Status.REQUESTED
    assert e.name == "Dr Outside"


def test_decide_external_approve_notifies_member(db):
    from formation.control import decide_external
    from notifications.models import Notification
    u = User.objects.create_user(email="dec@example.com", password="x")
    reviewer = User.objects.create_user(email="rev@example.com", password="x",
                                        is_staff=True)
    e = ExternalControlAnalyst.objects.create(
        member=u, name="Dr X", description="...")
    decide_external(e, approve=True, by=reviewer, note="ok")
    e.refresh_from_db()
    assert e.status == ExternalControlAnalyst.Status.APPROVED
    assert e.decided_by == reviewer
    assert Notification.objects.filter(recipient=u).exists()
