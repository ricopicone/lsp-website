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
    assert user.profile.is_faculty is False
    assert user.profile.default_billing_mode is None
    assert user.profile.bio == ""
    assert user.profile.public is False


@pytest.mark.django_db
def test_default_billing_mode_cleared_for_non_faculty():
    user = User.objects.create_user(email="bm@example.com")
    p = user.profile
    p.is_faculty = True
    p.default_billing_mode = Profile.BillingMode.PER_SEMINAR
    p.save()
    assert p.default_billing_mode == Profile.BillingMode.PER_SEMINAR

    p.is_faculty = False
    p.save()
    p.refresh_from_db()
    assert p.default_billing_mode is None


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


# --- Directory ---------------------------------------------------------------


def _mk_member(email, first, last, role, **extra):
    u = User.objects.create_user(email=email, first_name=first, last_name=last)
    p = u.profile
    p.role = role
    for k, v in extra.items():
        setattr(p, k, v)
    p.save()
    return u


@pytest.mark.django_db
def test_directory_lists_members_by_role_section(client):
    _mk_member("a@x.test", "Andre", "Patsalides", Profile.Role.ANALYST, location="Paris")
    _mk_member("c@x.test", "Cecile", "Gouffrant", Profile.Role.CANDIDATE, location="Philly")
    # External users must NOT show in the directory.
    _mk_member("g@x.test", "Guest", "Person", Profile.Role.EXTERNAL)
    resp = client.get("/directory/")
    assert resp.status_code == 200
    body = resp.content
    assert b"Analysts of the School" in body
    assert b"Candidate Analysts" in body
    assert b"Andre" in body and b"Patsalides" in body
    assert b"Cecile" in body and b"Gouffrant" in body
    assert b"Guest Person" not in body


@pytest.mark.django_db
def test_directory_detail_resolves_by_slug(client):
    _mk_member(
        "a@x.test", "Andre", "Patsalides", Profile.Role.ANALYST,
        bio="Founding member.", location="Paris, France",
        credentials="PhD", languages_spoken="French, English",
    )
    resp = client.get("/directory/andre-patsalides/")
    assert resp.status_code == 200
    body = resp.content
    assert b"Andre Patsalides" in body
    assert b"Paris, France" in body
    assert b"Founding member." in body
    assert b"PhD" in body
    assert b"French, English" in body
    # Public email defaults to login email when public_email is unset.
    assert b"a@x.test" in body


@pytest.mark.django_db
def test_directory_detail_404_for_unknown_slug(client):
    resp = client.get("/directory/no-such-person/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_profile_is_in_directory_for_member_roles():
    u = User.objects.create_user(email="a@x.test")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    assert u.profile.is_in_directory is True

    u.profile.role = Profile.Role.EXTERNAL
    u.profile.save()
    assert u.profile.is_in_directory is False


@pytest.mark.django_db
def test_profile_directory_slug_matches_url():
    u = User.objects.create_user(
        email="a@x.test", first_name="Andre", last_name="Patsalides"
    )
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    assert u.profile.directory_slug == "andre-patsalides"


@pytest.mark.django_db
def test_directory_detail_prefers_public_email_when_set(client):
    _mk_member(
        "login@x.test", "Sora", "Han", Profile.Role.PRE_CANDIDATE_SCHOLAR,
        public_email="public@x.test",
    )
    resp = client.get("/directory/sora-han/")
    body = resp.content
    assert b"public@x.test" in body
    assert b"login@x.test" not in body
