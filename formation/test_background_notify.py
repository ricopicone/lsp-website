import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_background_set_notifies_member():
    from formation import notifications as notify_formation
    from formation.models import BackgroundDetermination
    from notifications.categories import Category
    from notifications.models import Notification

    member = User.objects.create_user(email="m@example.com", password="x")
    row = BackgroundDetermination.objects.create(
        member=member, background="clinical", previous="unreviewed",
    )
    notify_formation.background_set(member, row)

    n = Notification.objects.get(recipient=member, category=Category.FORMATION_BACKGROUND)
    assert "clinical" in n.title.lower()
    assert "#control" in n.url
