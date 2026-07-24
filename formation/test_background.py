import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_background_determination_records_change():
    from formation.models import BackgroundDetermination

    member = User.objects.create_user(email="m@example.com", password="x")
    setter = User.objects.create_user(email="a@example.com", password="x")
    row = BackgroundDetermination.objects.create(
        member=member, background="clinical", previous="unreviewed",
        set_by=setter, note="Licensed clinical psychologist.",
    )
    assert row.created_at is not None
    assert list(member.background_determinations.all()) == [row]
