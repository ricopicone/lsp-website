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
def test_login_page_is_context_aware_for_event_registration(client):
    from datetime import date

    from events.models import Event

    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    resp = client.get(f"/accounts/login/?next=/events/{e.slug}/register/")
    content = resp.content.decode()
    assert "Working with Masochism" in content
    assert "Create a free account" in content


@pytest.mark.django_db
def test_login_page_does_not_promise_entry_to_a_members_only_event(client):
    """The funnel must not tell a stranger a free account gets them into an
    event it won't (task #566)."""
    from datetime import date

    from events.models import Event

    e = Event.objects.create(
        title="Members Evening", slug="members-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
    )
    content = client.get(
        f"/accounts/login/?next=/events/{e.slug}/register/"
    ).content.decode()
    assert "You don&#x27;t need to be a member" not in content
    assert "limited to members" in content
    # The account itself is still worth having, so the button stays.
    assert "Create a free account" in content


@pytest.mark.django_db
def test_signup_page_says_a_members_only_event_is_members_only(client):
    from datetime import date

    from events.models import Event

    e = Event.objects.create(
        title="Members Evening", slug="members-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
    )
    content = client.get(
        f"/accounts/signup/?next=/events/{e.slug}/register/"
    ).content.decode()
    assert "limited to members" in content


@pytest.mark.django_db
def test_login_page_generic_for_unrelated_or_bad_next(client):
    for nxt in ["/events/", "/events/no-such-event/register/",
                "https://evil.example/x", ""]:
        resp = client.get("/accounts/login/", {"next": nxt} if nxt else {})
        content = resp.content.decode()
        assert "Sign in to the Lacanian School." in content
        # The promoted signup button shows regardless of context.
        assert "Create a free account" in content


@pytest.mark.django_db
def test_login_page_generic_for_draft_event(client):
    from datetime import date

    from events.models import Event

    e = Event.objects.create(
        title="Hidden Draft", slug="hidden-draft",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        published=False,
    )
    resp = client.get(f"/accounts/login/?next=/events/{e.slug}/register/")
    assert "Hidden Draft" not in resp.content.decode()


@pytest.mark.django_db
def test_signup_page_is_context_aware_and_explains_membership(client):
    from datetime import date

    from events.models import Event

    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    resp = client.get(f"/accounts/signup/?next=/events/{e.slug}/register/")
    content = resp.content.decode()
    assert "Working with Masochism" in content
    assert "doesn't make you a member" in content

    # No event context: still shows the explainer, generic heading.
    resp = client.get("/accounts/signup/")
    content = resp.content.decode()
    assert "doesn't make you a member" in content
    assert "Create an account" in content


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
def test_directory_excludes_web_developer_badge(client):
    """Web Developer is technical operations, not a public school position —
    it must not badge the directory (task #482), like LSP Staff and Registrar."""
    from core.models import StaffRole

    u = _mk_member("dev@x.test", "Dev", "Ops", Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.WEB_DEVELOPER).holders.add(u)
    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(u)

    detail = client.get("/directory/dev-ops/").content
    assert b"Cartel Coordinator" in detail
    assert b"Web Developer" not in detail

    grid = client.get("/directory/").content
    assert b"Web Developer" not in grid


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


def _moa():
    """The Meeting of Analysts committee (seeded, Internal)."""
    from committees.models import Committee
    return Committee.objects.get(slug="meeting-of-analysts")


@pytest.mark.django_db
def test_directory_badges_applications_coordinator(client):
    """Task #481: the Applications Coordinator is an appointed position on the
    Meeting of Analysts, which has no public page — it must still badge, as the
    position alone (the Meeting is not named)."""
    moa = _moa()
    assert not moa.public, "fixture assumes the Meeting of Analysts is Internal"

    dana = _mk_member("dana@x.test", "Dana", "Coordinator", Profile.Role.ANALYST)
    moa.add_member(dana, role="applications_coordinator")
    _mk_member("plain2@x.test", "Plainer", "Person", Profile.Role.ANALYST)

    grid = client.get("/directory/").content
    assert b"Applications Coordinator" in grid
    assert grid.count(b"Applications Coordinator") == 1

    detail = client.get("/directory/dana-coordinator/").content
    assert b"Applications Coordinator" in detail
    # The badge names the position, not the Internal committee.
    assert b"Meeting of Analysts" not in detail

    other = client.get("/directory/plainer-person/").content
    assert b"Applications Coordinator" not in other


@pytest.mark.django_db
def test_directory_does_not_badge_derived_membership(client):
    """The load-bearing rule: badge appointed positions, never plain membership.
    Meeting-of-Analysts membership is auto-derived from the Analyst role, so
    badging it would stamp every analyst with a redundant committee name."""
    moa = _moa()
    member = _mk_member("mem@x.test", "Mem", "Bership", Profile.Role.ANALYST)
    moa.add_member(member, role="member")

    detail = client.get("/directory/mem-bership/").content
    assert b"Meeting of Analysts" not in detail


@pytest.mark.django_db
def test_directory_dedups_internal_officer_against_staff_role(client):
    """An Internal-committee officer whose position is also a StaffRole they hold
    gets one badge, using the StaffRole's editable display name."""
    from committees.models import Committee
    from core.models import StaffRole

    u = _mk_member("dee@x.test", "Dee", "Dupe", Profile.Role.ANALYST)
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.add(u)
    internal = Committee.objects.create(name="Audit", slug="audit", public=False)
    internal.add_member(u, role="treasurer")

    detail = client.get("/directory/dee-dupe/").content
    assert detail.count(b"Treasurer") == 1
    # The Internal committee itself is never named.
    assert b"Audit" not in detail


@pytest.mark.django_db
def test_directory_does_not_badge_non_committee_officer_roles(client):
    """Officer-ish roles on cartels/seminars (organizer, faculty, plus-one) are
    not school appointments and must not badge."""
    from workgroups.models import Workgroup, build_workgroup

    u = _mk_member("carl@x.test", "Carl", "Telist", Profile.Role.ANALYST)
    wg = build_workgroup(Workgroup.Kind.CARTEL, name="Some Cartel", slug="some-cartel")
    wg.add_member(u, role="organizer")

    detail = client.get("/directory/carl-telist/").content
    assert b"Organizer" not in detail
    assert b"Some Cartel" not in detail


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
    """A submission that clears every bot check and the content screen.

    The render stamp is backdated because the form is rejected if it comes
    back faster than a human could fill it (task #479), and the narrative is
    a realistic length — under 40 characters it would be held for review.
    """
    from datetime import timedelta

    from django.utils import timezone

    from accounts import antibot

    return {
        "name":                   "Alex Patient",
        "pronouns":               "they/them",
        "pronouns_other":         "",
        "email":                  "inquirer@example.com",
        "location":               "Brooklyn, NY",
        "language":               "English",
        "modality":               ["video"],
        "additional_information": (
            "Looking for a Lacanian analyst. I have been in therapy before "
            "and would like to work more deeply this time."
        ),
        antibot.HONEYPOT_FIELD:   "",
        antibot.TIMESTAMP_FIELD:  antibot.sign_timestamp(
            timezone.now() - timedelta(seconds=60),
        ),
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
def test_removed_member_is_not_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rm@example.com")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.standing = Profile.Standing.REMOVED
    user.profile.save()
    assert is_lsp_member(user) is False


@pytest.mark.django_db
def test_resigned_member_is_not_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rs@example.com")
    user.profile.role = Profile.Role.ANALYST
    user.profile.standing = Profile.Standing.RESIGNED
    user.profile.save()
    assert is_lsp_member(user) is False


@pytest.mark.django_db
def test_retired_member_stays_lsp_member():
    from accounts.permissions import is_lsp_member
    user = User.objects.create_user(email="rt@example.com")
    user.profile.role = Profile.Role.ANALYST
    user.profile.standing = Profile.Standing.RETIRED
    user.profile.save()
    assert is_lsp_member(user) is True


@pytest.mark.django_db
def test_admin_deceased_on_is_readonly_no_partial_workflow(client):
    """task #451 fix-first: the Django admin must not offer a partial
    'deceased' path that disables login without running the full
    accounts.lifecycle.set_deceased() workflow (auto-waive open charges +
    referral delisting). deceased_on is readonly on both the User-page
    ProfileInline and the standalone ProfileAdmin; a crafted POST attempting
    to set it must be silently ignored by Django's readonly-field handling,
    leaving the open charge owed and the referral listing active."""
    from payments.models import Charge
    from referrals.models import ReferralListMember

    # The admin classes declare the field readonly (belt-and-suspenders with
    # the functional check below).
    from .admin import ProfileAdmin, ProfileInline
    assert "deceased_on" in ProfileInline.readonly_fields
    assert "deceased_on" in ProfileAdmin.readonly_fields

    admin_user = User.objects.create_superuser(
        email="admin451@example.com", password="not-a-real-password",
    )
    client.force_login(admin_user)

    target = User.objects.create_user(email="target451@example.com")
    target.profile.role = Profile.Role.ANALYST
    target.profile.save()
    charge = Charge.objects.create(
        user=target, category=Charge.Category.DUES, amount="100.00",
        effective_date=date(2026, 9, 1),
    )
    listing = ReferralListMember.objects.create(user=target, is_active=True)

    resp = client.get(f"/admin/accounts/user/{target.pk}/change/")
    assert resp.status_code == 200
    # Build a minimal valid POST from the rendered forms, then attempt to
    # smuggle a deceased_on value into the readonly inline field.
    data = {}
    for field in resp.context["adminform"].form:
        data[field.html_name] = field.value() or ""
    for fs in resp.context["inline_admin_formsets"]:
        for k, v in fs.formset.management_form.initial.items():
            data[f"{fs.formset.prefix}-{k}"] = v
        for form in fs.formset.forms:
            for field in form:
                if field.name == "headshot":
                    continue  # unset FileField chokes the multipart encoder
                value = field.value()
                data[field.html_name] = "" if value is None else value
    data["profile-0-deceased_on"] = "2026-07-22"

    resp2 = client.post(
        f"/admin/accounts/user/{target.pk}/change/", data, follow=True,
    )
    assert resp2.status_code == 200

    target.refresh_from_db()
    assert target.profile.deceased_on is None  # readonly: injection ignored
    assert target.is_active is True  # login stays enabled

    charge.refresh_from_db()
    assert charge.status == Charge.Status.OPEN  # not auto-waived

    listing.refresh_from_db()
    assert listing.is_active is True  # not delisted


@pytest.mark.django_db
def test_directory_excludes_removed_and_resigned_keeps_deceased():
    from datetime import date
    for email, standing, deceased in [
        ("active@x.test", Profile.Standing.ACTIVE, None),
        ("removed@x.test", Profile.Standing.REMOVED, None),
        ("resigned@x.test", Profile.Standing.RESIGNED, None),
        ("deceased@x.test", Profile.Standing.ACTIVE, date(2026, 7, 22)),
    ]:
        u = User.objects.create_user(email=email, first_name="T", last_name=email[:4])
        u.profile.role = Profile.Role.ANALYST
        u.profile.standing = standing
        u.profile.public = True
        u.profile.deceased_on = deceased
        u.profile.save()

    from accounts.views import _directory_qs
    listed = {p.user.email for p in _directory_qs()}
    assert "active@x.test" in listed
    assert "deceased@x.test" in listed       # deceased stays listed
    assert "removed@x.test" not in listed
    assert "resigned@x.test" not in listed


@pytest.mark.django_db
def test_directory_shows_memorial_marker_for_deceased(client):
    from datetime import date
    u = User.objects.create_user(email="memoriam@x.test", first_name="Jane", last_name="Doe")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()

    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "In memoriam" in body


@pytest.mark.django_db
def test_directory_detail_hides_referral_cta_for_deceased(client):
    from datetime import date
    u = User.objects.create_user(email="nocta@x.test", first_name="John", last_name="Roe")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.public_email = "john@x.test"
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()

    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    body = resp.content.decode()
    # No contact email link for a deceased member.
    assert "mailto:john@x.test" not in body


@pytest.mark.django_db
def test_find_an_analyst_map_excludes_retired_and_deceased(client):
    """The Find-an-Analyst map is a referral surface, not the directory grid:
    retired and deceased members must not appear as pins, even though both
    stay in the directory grid (task #451)."""
    from django.urls import reverse

    from accounts.views import _directory_qs

    def _make(email, last, standing, deceased_on=None):
        u = User.objects.create_user(email=email, first_name="T", last_name=last)
        u.profile.role = Profile.Role.ANALYST
        u.profile.standing = standing
        u.profile.public = True
        u.profile.deceased_on = deceased_on
        u.profile.location = "Somewhere, CA"
        u.profile.location_lat = 37.0
        u.profile.location_lng = -122.0
        u.profile.save()
        return u

    active = _make("active-map@x.test", "Active", Profile.Standing.ACTIVE)
    retired = _make("retired-map@x.test", "Retired", Profile.Standing.RETIRED)
    deceased = _make(
        "deceased-map@x.test", "Deceased", Profile.Standing.ACTIVE,
        deceased_on=date(2026, 7, 22),
    )

    data = client.get(reverse("find_an_analyst_pins")).json()
    names = {pin["name"] for pin in data["pins"]}
    assert "T Active" in names
    assert "T Retired" not in names
    assert "T Deceased" not in names

    # But the directory grid still shows the retired and deceased members —
    # only the map narrows further.
    directory_emails = {p.user.email for p in _directory_qs()}
    assert active.email in directory_emails
    assert retired.email in directory_emails
    assert deceased.email in directory_emails


@pytest.mark.django_db
def test_is_retired_property():
    u = User.objects.create_user(email="rtd@example.com")
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.save()
    assert u.profile.is_retired is True
    u.profile.standing = Profile.Standing.ACTIVE
    u.profile.save()
    assert u.profile.is_retired is False


@pytest.mark.django_db
def test_directory_shows_retired_marker(client):
    u = User.objects.create_user(email="rtdir@example.com", first_name="Rhea", last_name="Tired")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.save()
    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    assert resp.status_code == 200
    assert "Retired" in resp.content.decode()


@pytest.mark.django_db
def test_directory_active_member_has_no_retired_marker(client):
    u = User.objects.create_user(email="act@example.com", first_name="Ann", last_name="Active")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.save()
    resp = client.get(f"/directory/{u.profile.directory_slug}/")
    body = resp.content.decode()
    # The word may appear in nav/other copy; assert the marker element text isn't present.
    assert "Retired</span>" not in body and "Retired</p>" not in body


@pytest.mark.django_db
def test_directory_list_shows_retired_marker_on_card(client):
    u = User.objects.create_user(email="rtcard@x.test", first_name="Rhea", last_name="Tired")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.save()
    resp = client.get("/directory/")
    assert resp.status_code == 200
    assert "Retired</span>" in resp.content.decode()


@pytest.mark.django_db
def test_directory_list_shows_memorial_marker_on_card(client):
    from datetime import date
    u = User.objects.create_user(email="memcard@x.test", first_name="Jane", last_name="Doe")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()
    resp = client.get("/directory/")
    assert resp.status_code == 200
    assert "In memoriam" in resp.content.decode()


@pytest.mark.django_db
def test_directory_card_retired_and_deceased_shows_only_memorial(client):
    from datetime import date
    u = User.objects.create_user(email="both@x.test", first_name="Both", last_name="Marks")
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = True
    u.profile.standing = Profile.Standing.RETIRED
    u.profile.deceased_on = date(2026, 7, 22)
    u.profile.save()
    body = client.get("/directory/").content.decode()
    assert "In memoriam" in body
    assert "Retired</span>" not in body  # deceased takes precedence


def test_safe_next_rejects_hostful_and_backslash_urls(rf):
    from accounts.views import _safe_next

    assert _safe_next(rf.get("/", {"next": "/dues/"})) == "/dues/"
    for evil in ("//evil.example", "/\\evil.example", "http://evil.example",
                 "\\/evil.example", ""):
        assert _safe_next(rf.get("/", {"next": evil})) is None, evil
