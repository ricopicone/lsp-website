import pytest

from accounts.models import Profile, User

pytestmark = pytest.mark.django_db


def _member():
    return User.objects.create_user(email="m@example.com", password="x")


def test_set_background_writes_row_updates_profile_and_notifies():
    from formation.background import set_background
    from formation.models import BackgroundDetermination
    from notifications.categories import Category
    from notifications.models import Notification

    member = _member()
    setter = User.objects.create_user(email="a@example.com", password="x")
    row = set_background(member, Profile.FormationBackground.CLINICAL,
                         by=setter, note="Licensed clinician.")

    member.profile.refresh_from_db()
    assert member.profile.formation_background == Profile.FormationBackground.CLINICAL
    assert row.previous == Profile.FormationBackground.UNREVIEWED
    assert row.note == "Licensed clinician."
    assert BackgroundDetermination.objects.filter(member=member).count() == 1
    assert Notification.objects.filter(
        recipient=member, category=Category.FORMATION_BACKGROUND).exists()


def test_set_background_noop_when_unchanged():
    from formation.background import set_background
    from formation.models import BackgroundDetermination

    member = _member()
    member.profile.formation_background = Profile.FormationBackground.ACADEMIC
    member.profile.save()

    assert set_background(member, Profile.FormationBackground.ACADEMIC, by=None) is None
    assert BackgroundDetermination.objects.filter(member=member).count() == 0
