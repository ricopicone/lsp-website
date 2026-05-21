"""Tests for the accounts app: the custom user model and profiles."""

import pytest

from .models import Profile, User


@pytest.mark.django_db
def test_create_user_with_email():
    user = User.objects.create_user(
        email="member@example.com",
        password="not-a-real-password",
    )
    assert user.pk is not None
    assert user.email == "member@example.com"
    assert user.is_staff is False
    assert user.is_superuser is False


@pytest.mark.django_db
def test_create_superuser():
    admin = User.objects.create_superuser(
        email="admin@example.com",
        password="not-a-real-password",
    )
    assert admin.is_staff is True
    assert admin.is_superuser is True


@pytest.mark.django_db
def test_profile_created_automatically():
    user = User.objects.create_user(
        email="auto@example.com",
        password="not-a-real-password",
    )
    assert hasattr(user, "profile")
    assert user.profile.role == Profile.Role.EXTERNAL
    assert user.profile.tuition_paying is False


@pytest.mark.django_db
def test_user_str_is_email():
    user = User.objects.create_user(
        email="str@example.com",
        password="not-a-real-password",
    )
    assert str(user) == "str@example.com"


@pytest.mark.django_db
def test_user_admin_add_page_loads(client):
    admin_user = User.objects.create_superuser(
        email="root@example.com",
        password="not-a-real-password",
    )
    client.force_login(admin_user)
    response = client.get("/admin/accounts/user/add/")
    assert response.status_code == 200
