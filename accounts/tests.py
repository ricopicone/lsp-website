"""Tests for the accounts app: the custom user model and profiles."""

from datetime import date

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
    assert user.profile.owes_tuition is False  # default role is EXTERNAL
    assert user.profile.is_faculty is False
    assert user.profile.default_billing_mode is None
    assert user.profile.bio == ""
    assert user.profile.public is True  # listed by default; members may opt out


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
def test_directory_badges_board_appointee_staff_roles(client):
    """Board-appointed StaffRole holders get a coordinator badge on both the
    grid and the detail page; non-holders don't."""
    from core.models import StaffRole

    casey = _mk_member("casey@x.test", "Casey", "Butcher", Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(casey)
    _mk_member("plain@x.test", "Plain", "Member", Profile.Role.ANALYST)

    grid = client.get("/directory/").content
    assert b"Cartel Coordinator" in grid
    # Only Casey holds it.
    assert grid.count(b"Cartel Coordinator") == 1

    detail = client.get("/directory/casey-butcher/").content
    assert b"Cartel Coordinator" in detail
    other = client.get("/directory/plain-member/").content
    assert b"Cartel Coordinator" not in other


@pytest.mark.django_db
def test_directory_excludes_lsp_staff_badge(client):
    """LSP Staff is an internal access designation, not a public position —
    it must not badge the directory, even though other roles do."""
    from core.models import StaffRole

    u = _mk_member("stan@x.test", "Stan", "Staffer", Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.LSP_STAFF).holders.add(u)
    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(u)

    detail = client.get("/directory/stan-staffer/").content
    assert b"Cartel Coordinator" in detail
    assert b"LSP Staff" not in detail


@pytest.mark.django_db
def test_directory_dedups_staff_role_against_committee_officer(client):
    """A Treasurer who is also the Board's Treasurer gets only the more
    informative committee officer badge, not a redundant standalone one."""
    from committees.models import Committee
    from core.models import StaffRole

    u = _mk_member("tess@x.test", "Tess", "Banks", Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.add(u)
    committee = Committee.objects.create(name="Finance", slug="finance", public=True)
    committee.add_member(u, role="treasurer")

    detail = client.get("/directory/tess-banks/").content
    assert b"Finance" in detail
    # "Finance · Treasurer" only — no extra standalone "Treasurer" badge.
    assert detail.count(b"Treasurer") == 1


@pytest.mark.django_db
def test_directory_styles_board_chair_as_president(client):
    """Task #428: the Board's Chair / Co-chair read President / Vice President on
    the directory too (not just the About page), and the redundant standalone
    President / Vice-President StaffRole badge is dropped — one consistent title."""
    from committees.models import Committee
    from core.models import StaffRole

    board, _ = Committee.objects.get_or_create(
        slug="board", defaults={"name": "Board of Directors"}
    )
    board.public = True
    board.save(update_fields=["public"])

    pres = _mk_member("prez@x.test", "Prez", "Ident", Profile.Role.ANALYST)
    board.add_member(pres, role="chair")
    StaffRole.objects.get(key=StaffRole.PRESIDENT).holders.add(pres)

    detail = client.get("/directory/prez-ident/").content
    assert b"President" in detail
    # The generic enum label must not leak, and there's a single "President".
    assert b"Chair" not in detail
    assert detail.count(b"President") == 1


def test_split_location_single():
    from accounts.geocoding import split_location
    assert split_location("Paris, France") == ["Paris, France"]
    assert split_location("Beijing, China") == ["Beijing, China"]


def test_split_location_ampersand_with_shared_suffix():
    from accounts.geocoding import split_location
    assert split_location("San Francisco & Palo Alto, CA") == [
        "San Francisco, CA", "Palo Alto, CA",
    ]


def test_split_location_keeps_complete_addresses_intact():
    from accounts.geocoding import split_location
    assert split_location("Paris, France & New York, USA") == [
        "Paris, France", "New York, USA",
    ]


def test_split_location_slash_and_and():
    from accounts.geocoding import split_location
    assert split_location("Berkeley / Oakland, CA") == ["Berkeley, CA", "Oakland, CA"]
    assert split_location("San Francisco and Palo Alto, CA") == [
        "San Francisco, CA", "Palo Alto, CA",
    ]


def test_split_location_semicolon_keeps_full_addresses():
    from accounts.geocoding import split_location
    assert split_location("Berlin, Germany; London, UK") == [
        "Berlin, Germany", "London, UK",
    ]


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


@pytest.mark.django_db
def test_directory_card_shows_faculty_badge(client):
    _mk_member(
        "f@x.test", "Faye", "Teacher", Profile.Role.ANALYST,
        is_faculty=True,
    )
    _mk_member(
        "n@x.test", "Nora", "Notfaculty", Profile.Role.ANALYST,
        is_faculty=False,
    )
    body = client.get("/directory/").content
    # Faculty badge is in the card for the faculty member, not the other.
    assert b"Faculty" in body
    # Check it's actually next to Faye, not just an arbitrary appearance —
    # the card layout puts the badge in the same block as the name.
    assert body.count(b"Faculty") == 1


@pytest.mark.django_db
def test_directory_detail_shows_faculty_badge(client):
    _mk_member(
        "f@x.test", "Faye", "Teacher", Profile.Role.ANALYST,
        is_faculty=True,
    )
    body = client.get("/directory/faye-teacher/").content
    assert b"Faculty" in body


# ---- Find-an-Analyst referral form -------------------------------------


def _valid_referral_post():
    return {
        "name":                   "Alex Patient",
        "pronouns":               "they/them",
        "pronouns_other":         "",
        "email":                  "inquirer@example.com",
        "location":               "Brooklyn, NY",
        "language":               "English",
        "modality":               ["video"],
        "additional_information": "Looking for a Lacanian analyst.",
        "website":                "",  # honeypot
    }


@pytest.mark.django_db
def test_find_an_analyst_post_tracks_request_and_sends_emails(
    client, mailoutbox, settings,
):
    settings.REFERRALS_EMAIL = "referrals@lacanschool.org"
    resp = client.post("/find-an-analyst/", _valid_referral_post(), follow=False)
    assert resp.status_code == 302
    assert resp.url.endswith("?submitted=1#submitted")
    assert len(mailoutbox) == 2

    # The submission is now a tracked ReferralRequest (referrals app).
    from referrals.models import ReferralRequest

    req = ReferralRequest.objects.get(email="inquirer@example.com")
    assert req.name == "Alex Patient"
    assert req.status == ReferralRequest.Status.ACKNOWLEDGED

    # The coordinator inquiry: To = referrals, Reply-To = inquirer.
    inquiry = next(
        m for m in mailoutbox if m.to == ["referrals@lacanschool.org"]
    )
    assert "Alex Patient" in inquiry.subject
    assert req.reference in inquiry.subject
    assert inquiry.reply_to == ["inquirer@example.com"]
    assert "Brooklyn, NY" in inquiry.body

    # The acknowledgment (the coordinator's editable process reply):
    # To = inquirer, Reply-To = referrals.
    ack = next(m for m in mailoutbox if m.to == ["inquirer@example.com"])
    assert ack.reply_to == ["referrals@lacanschool.org"]
    assert "Dear Alex Patient," in ack.body
    assert "Diana C. Cuello" in ack.body


@pytest.mark.django_db
def test_find_an_analyst_ack_failure_does_not_block_redirect(
    client, mailoutbox, settings, monkeypatch,
):
    """If the acknowledgment email fails to send, the form still succeeds —
    the request is persisted and the coordinator received the inquiry."""
    settings.REFERRALS_EMAIL = "referrals@lacanschool.org"
    from referrals import services as referral_services

    def _boom(*_args, **_kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(referral_services.emails, "send_to_requester", _boom)
    resp = client.post("/find-an-analyst/", _valid_referral_post(), follow=False)
    assert resp.status_code == 302
    # Inquiry to coordinator still went through, and the request is tracked.
    assert any(m.to == ["referrals@lacanschool.org"] for m in mailoutbox)
    from referrals.models import ReferralRequest

    assert ReferralRequest.objects.filter(email="inquirer@example.com").exists()


@pytest.mark.django_db
def test_new_standing_values_exist():
    assert Profile.Standing.RETIRED == "retired"
    assert Profile.Standing.REMOVED == "removed"
    # Emeritus is kept, not replaced.
    assert Profile.Standing.EMERITUS == "emeritus"


@pytest.mark.django_db
def test_non_member_standings_set():
    assert Profile.NON_MEMBER_STANDINGS == frozenset({"resigned", "removed"})


@pytest.mark.django_db
def test_setting_deceased_on_disables_login_on_save():
    user = User.objects.create_user(email="d@example.com")
    assert user.is_active is True
    user.profile.deceased_on = date(2026, 7, 22)
    user.profile.save()
    user.refresh_from_db()
    assert user.is_active is False
    assert user.profile.is_deceased is True


@pytest.mark.django_db
def test_clearing_deceased_on_reenables_login_on_save():
    user = User.objects.create_user(email="d2@example.com")
    user.profile.deceased_on = date(2026, 7, 22)
    user.profile.save()
    user.profile.deceased_on = None
    user.profile.save()
    user.refresh_from_db()
    assert user.is_active is True


@pytest.mark.django_db
def test_is_active_member_predicate():
    user = User.objects.create_user(email="m@example.com")
    p = user.profile
    p.role = Profile.Role.ANALYST
    p.standing = Profile.Standing.ACTIVE
    p.save()
    assert p.is_active_member is True
    p.standing = Profile.Standing.REMOVED
    p.save()
    assert p.is_active_member is False
    p.standing = Profile.Standing.RETIRED
    p.save()
    assert p.is_active_member is True  # retired is still a member
