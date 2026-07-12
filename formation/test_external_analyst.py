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
