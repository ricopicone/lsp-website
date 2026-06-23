"""Tests for analyst availability: data model + services (Phase 1) and the
Applications Coordinator console (Phase 2)."""

from __future__ import annotations

import datetime as _dt
from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from notifications.models import Notification

from . import services
from .models import (
    AnalystFunction,
    AvailabilitySettings,
    AvailabilitySpan,
    ReminderTemplate,
)

pytestmark = pytest.mark.django_db

Status = AvailabilitySpan.Status


# ---- Fixtures ------------------------------------------------------------


@pytest.fixture
def analyst():
    user = User.objects.create_user(
        email="analyst@example.com", password="pw",
        first_name="Anna", last_name="Analyst",
    )
    profile = user.profile
    profile.role = Profile.Role.ANALYST
    profile.save()
    return profile


@pytest.fixture
def interviews():
    return AnalystFunction.objects.get(slug="application-interviews")


# ---- Seed migration ------------------------------------------------------


def test_four_functions_seeded():
    slugs = list(
        AnalystFunction.objects.order_by("display_order").values_list("slug", flat=True)
    )
    assert slugs == [
        "application-interviews",
        "advisor",
        "control-analysis",
        "personal-analysis",
    ]


def test_column_label_falls_back_to_name(interviews):
    assert interviews.column_label == "Application Interviews"
    interviews.short_label = "Interviews"
    assert interviews.column_label == "Interviews"


# ---- set_availability transitions ---------------------------------------


def test_set_availability_opens_a_span(analyst, interviews):
    span = services.set_availability(
        analyst, interviews, Status.YES,
        on_date=_dt.date(2026, 9, 1), source=AvailabilitySpan.Source.IMPORT,
    )
    assert span.is_open
    assert span.status == Status.YES
    assert services.current_status(analyst, interviews) == Status.YES


def test_changing_status_closes_old_span_and_opens_new(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2027, 1, 1))

    spans = list(
        AvailabilitySpan.objects.filter(profile=analyst, function=interviews)
        .order_by("start_date")
    )
    assert len(spans) == 2
    assert spans[0].status == Status.YES
    assert spans[0].end_date == _dt.date(2026, 12, 31)  # closed day before the change
    assert spans[1].status == Status.NO
    assert spans[1].is_open
    assert services.current_status(analyst, interviews) == Status.NO


def test_idempotent_when_status_unchanged(analyst, interviews):
    first = services.set_availability(analyst, interviews, Status.YES)
    again = services.set_availability(analyst, interviews, Status.YES)
    assert first.pk == again.pk
    assert AvailabilitySpan.objects.filter(profile=analyst, function=interviews).count() == 1


def test_note_is_per_analyst_with_history(analyst):
    assert services.current_note(analyst) == ""
    services.set_note(analyst, "Except Oct-Dec 2026")
    assert services.current_note(analyst) == "Except Oct-Dec 2026"
    # Unchanged → no new row.
    assert services.set_note(analyst, "Except Oct-Dec 2026") is None
    # Changed → appends, history preserved.
    services.set_note(analyst, "Available all year")
    assert services.current_note(analyst) == "Available all year"
    assert len(services.note_history(analyst)) == 2


def test_unknown_is_default_when_never_set(analyst, interviews):
    assert services.current_status(analyst, interviews) == Status.UNKNOWN


def test_current_map_returns_open_spans_only(analyst, interviews):
    advisor = AnalystFunction.objects.get(slug="advisor")
    services.set_availability(analyst, interviews, Status.YES)
    services.set_availability(analyst, advisor, Status.NO)
    mapping = services.current_map(analyst)
    assert mapping == {interviews.id: Status.YES, advisor.id: Status.NO}


# ---- The one-open-span invariant -----------------------------------------


def test_db_constraint_forbids_two_open_spans(analyst, interviews):
    AvailabilitySpan.objects.create(
        profile=analyst, function=interviews, status=Status.YES,
        start_date=_dt.date(2026, 9, 1),
    )
    with pytest.raises(IntegrityError):
        AvailabilitySpan.objects.create(
            profile=analyst, function=interviews, status=Status.NO,
            start_date=_dt.date(2026, 10, 1),
        )


# ---- coverage_fraction (credit) ------------------------------------------


def test_coverage_full_year(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    # Available across the whole AY 2026-2027 window, asked about after it ends.
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    assert frac == pytest.approx(1.0)


def test_coverage_half_year(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2027, 3, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    # Sept 1 2026 → Mar 1 2027 is roughly half of a Sept→Sept year.
    assert 0.45 < frac < 0.55


def test_coverage_open_span_accrues_only_to_as_of(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 9, 1))
    # Halfway through the year: only the elapsed portion counts.
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 3, 1)
    )
    assert 0.45 < frac < 0.55


def test_coverage_upcoming_year_is_zero(analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES, on_date=_dt.date(2026, 6, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2026, 6, 15)
    )
    assert frac == 0.0


def test_coverage_ignores_non_yes_status(analyst, interviews):
    services.set_availability(analyst, interviews, Status.NO, on_date=_dt.date(2026, 9, 1))
    frac = services.coverage_fraction(
        analyst, interviews, "2026-2027", as_of=_dt.date(2027, 9, 1)
    )
    assert frac == 0.0


# ---- Eligibility ----------------------------------------------------------


def test_only_analysts_are_eligible(analyst):
    assert services.is_eligible(analyst) is True
    assert analyst in services.eligible_profiles()


def test_candidate_is_not_eligible():
    user = User.objects.create_user(email="c@example.com", password="pw")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()
    assert services.is_eligible(user.profile) is False
    assert user.profile not in services.eligible_profiles()


# ---- Phase 2: the coordinator console ------------------------------------


@pytest.fixture
def coordinator(client):
    user = User.objects.create_user(
        email="cecile@example.com", password="pw",
        first_name="Cecile", last_name="Gouffrant",
    )
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.APPLICATIONS_COORDINATOR,
        defaults={"name": "Applications Coordinator"},
    )
    role.holders.add(user)
    client.force_login(user)
    return user


def test_console_blocks_non_coordinator(client):
    user = User.objects.create_user(email="nobody@example.com", password="pw")
    client.force_login(user)
    resp = client.get(reverse("availability:grid"))
    assert resp.status_code == 403


def test_grid_lists_analysts_only(client, coordinator, analyst):
    # a non-analyst who should NOT appear
    other = User.objects.create_user(email="cand@example.com", password="pw")
    other.profile.role = Profile.Role.CANDIDATE
    other.profile.save()

    resp = client.get(reverse("availability:grid"))
    assert resp.status_code == 200
    assert b"Anna Analyst" in resp.content
    assert b"cand@example.com" not in resp.content


def test_grid_save_records_changes(client, coordinator, analyst, interviews):
    advisor = AnalystFunction.objects.get(slug="advisor")
    resp = client.post(reverse("availability:grid"), {
        f"cell_{analyst.pk}_{interviews.pk}": Status.YES,
        f"cell_{analyst.pk}_{advisor.pk}": Status.NO,
    })
    assert resp.status_code == 302
    assert services.current_status(analyst, interviews) == Status.YES
    assert services.current_status(analyst, advisor) == Status.NO
    span = AvailabilitySpan.objects.get(
        profile=analyst, function=interviews, end_date__isnull=True
    )
    assert span.source == AvailabilitySpan.Source.COORDINATOR
    assert span.created_by == coordinator


def test_grid_save_is_noop_when_unchanged(client, coordinator, analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES)
    before = AvailabilitySpan.objects.count()
    client.post(reverse("availability:grid"), {
        f"cell_{analyst.pk}_{interviews.pk}": Status.YES,
    })
    assert AvailabilitySpan.objects.count() == before


def test_analyst_page_and_cell_save(client, coordinator, analyst, interviews):
    url = reverse("availability:analyst", args=[analyst.pk])
    assert client.get(url).status_code == 200
    resp = client.post(url, {
        "action": "status", "function": interviews.pk, "status": Status.YES,
    })
    assert resp.status_code == 302
    span = AvailabilitySpan.objects.get(
        profile=analyst, function=interviews, end_date__isnull=True
    )
    assert span.status == Status.YES


def test_analyst_page_note_save(client, coordinator, analyst):
    url = reverse("availability:analyst", args=[analyst.pk])
    resp = client.post(url, {"action": "note", "note": "Except Oct-Dec 2026"})
    assert resp.status_code == 302
    assert services.current_note(analyst) == "Except Oct-Dec 2026"


def test_overview_renders(client, coordinator, analyst, interviews):
    services.set_availability(analyst, interviews, Status.YES)
    resp = client.get(reverse("availability:overview"))
    assert resp.status_code == 200
    assert b"Current coverage" in resp.content
    assert b"coverage-series" in resp.content


def test_grid_note_column_save(client, coordinator, analyst):
    resp = client.post(reverse("availability:grid"), {
        f"note_{analyst.pk}": "Applications coordinator",
    })
    assert resp.status_code == 302
    assert services.current_note(analyst) == "Applications coordinator"


def test_send_reminders_notifies_and_emails(
    client, coordinator, analyst, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("availability:send_reminders"))
    assert resp.status_code == 302
    assert Notification.objects.filter(
        recipient=analyst.user, category="availability_review"
    ).exists()
    assert len(mail.outbox) == 1
    assert analyst.user.email in mail.outbox[0].to
    # Replies reach the Applications Coordinator's mailbox.
    assert mail.outbox[0].reply_to == ["applications@lacanschool.org"]


def test_reminder_email_substitutes_coordinator_token(
    client, coordinator, analyst, django_capture_on_commit_callbacks
):
    # Coordinator's name should replace {applications_coordinator} in the body.
    ReminderTemplate.objects.update_or_create(
        key=ReminderTemplate.Key.REVIEW_REQUEST,
        defaults={"subject": "Review", "body": "Hi {name}, from {applications_coordinator}."},
    )
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("availability:send_reminders"))
    assert "Cecile Gouffrant" in mail.outbox[0].body
    assert "{applications_coordinator}" not in mail.outbox[0].body


def test_auto_reminder_command_respects_mode_and_runs_once(
    coordinator, analyst, django_capture_on_commit_callbacks
):
    from django.core.management import call_command

    cfg = AvailabilitySettings.load()
    cfg.reminder_mode = AvailabilitySettings.Mode.REVIEW
    cfg.save()
    # Review-first: nothing sent.
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_availability_reminders", stdout=StringIO())
    assert len(mail.outbox) == 0

    cfg.reminder_mode = AvailabilitySettings.Mode.AUTO
    cfg.save()
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_availability_reminders", stdout=StringIO())
    assert len(mail.outbox) == 1
    # Second run in the same AY is a no-op.
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_availability_reminders", stdout=StringIO())
    assert len(mail.outbox) == 1


def test_settings_save(client, coordinator):
    assert client.get(reverse("availability:settings")).status_code == 200
    resp = client.post(reverse("availability:settings"), {
        "reminder_mode": AvailabilitySettings.Mode.AUTO,
    })
    assert resp.status_code == 302
    assert AvailabilitySettings.load().reminder_mode == AvailabilitySettings.Mode.AUTO


def test_template_edit_save(client, coordinator):
    assert client.get(reverse("availability:templates")).status_code == 200
    resp = client.post(reverse("availability:templates"), {
        "subject": "Reminder", "body": "Hi {name}, update at {update_url}.",
    })
    assert resp.status_code == 302
    tmpl = ReminderTemplate.get(ReminderTemplate.Key.REVIEW_REQUEST)
    assert tmpl.subject == "Reminder"


# ---- Phase 5: the import command -----------------------------------------


def _make_analyst(first, last):
    user = User.objects.create_user(
        email=f"{first}.{last}@example.com".lower(), password="pw",
        first_name=first, last_name=last,
    )
    user.profile.role = Profile.Role.ANALYST
    user.profile.save()
    return user.profile


def _write_csv(tmp_path, body):
    path = tmp_path / "sheet.csv"
    path.write_text(body, encoding="utf-8")
    return str(path)


_HEADER = "Analyst,Application Interviews,Advisor,Control analysis,Personal analysis,Notes\n"


def test_import_creates_spans(tmp_path):
    rogers = _make_analyst("Annie", "Rogers")
    csv_path = _write_csv(tmp_path, _HEADER + "Annie Rogers,Y,Y,N,N,\n")

    call_command("import_analyst_availability", csv_path, stdout=StringIO())

    interviews = AnalystFunction.objects.get(slug="application-interviews")
    control = AnalystFunction.objects.get(slug="control-analysis")
    assert services.current_status(rogers, interviews) == Status.YES
    assert services.current_status(rogers, control) == Status.NO
    span = AvailabilitySpan.objects.get(
        profile=rogers, function=interviews, end_date__isnull=True
    )
    assert span.source == AvailabilitySpan.Source.IMPORT


def test_import_sets_per_analyst_note(tmp_path):
    swales = _make_analyst("Stephanie", "Swales")
    csv_path = _write_csv(
        tmp_path, _HEADER + "Stephanie Swales,Y,Y,Y,Y,Except Oct-Dec 2026\n"
    )
    call_command("import_analyst_availability", csv_path, stdout=StringIO())
    assert services.current_note(swales) == "Except Oct-Dec 2026"


def test_import_reports_unmatched_analyst(tmp_path):
    csv_path = _write_csv(tmp_path, _HEADER + "Nobody Here,Y,Y,Y,Y,\n")
    out = StringIO()
    call_command("import_analyst_availability", csv_path, stdout=out)
    assert "not matched" in out.getvalue()
    assert "Nobody Here" in out.getvalue()
    assert AvailabilitySpan.objects.count() == 0


def test_import_dry_run_writes_nothing(tmp_path):
    _make_analyst("Annie", "Rogers")
    csv_path = _write_csv(tmp_path, _HEADER + "Annie Rogers,Y,Y,N,N,\n")
    out = StringIO()
    call_command("import_analyst_availability", csv_path, "--dry-run", stdout=out)
    assert "Dry run" in out.getvalue()
    assert AvailabilitySpan.objects.count() == 0


def test_import_is_idempotent(tmp_path):
    _make_analyst("Annie", "Rogers")
    csv_path = _write_csv(tmp_path, _HEADER + "Annie Rogers,Y,Y,N,N,\n")
    call_command("import_analyst_availability", csv_path, stdout=StringIO())
    count = AvailabilitySpan.objects.count()
    call_command("import_analyst_availability", csv_path, stdout=StringIO())
    assert AvailabilitySpan.objects.count() == count  # no churn on re-run


def test_import_start_date_sets_span_start(tmp_path):
    rogers = _make_analyst("Annie", "Rogers")
    csv_path = _write_csv(tmp_path, _HEADER + "Annie Rogers,Y,N,N,N,\n")
    call_command(
        "import_analyst_availability", csv_path, "--start", "2026-05-20",
        stdout=StringIO(),
    )
    interviews = AnalystFunction.objects.get(slug="application-interviews")
    span = AvailabilitySpan.objects.get(profile=rogers, function=interviews)
    assert span.start_date == _dt.date(2026, 5, 20)


def test_import_rejects_unknown_column(tmp_path):
    csv_path = _write_csv(tmp_path, "Analyst,Bogus Column\nAnnie Rogers,Y\n")
    with pytest.raises(CommandError):
        call_command("import_analyst_availability", csv_path, stdout=StringIO())


# ---- Phase 4: member surfacing -------------------------------------------


def _login(client, email="m@example.com"):
    user = User.objects.create_user(email=email, password="pw")
    client.force_login(user)
    return user


def test_availability_table_requires_login(client):
    resp = client.get(reverse("directory_availability"))
    assert resp.status_code == 302  # redirected to login


def test_availability_table_lists_public_analysts(client, analyst, interviews):
    analyst.public = True
    analyst.save()
    services.set_availability(analyst, interviews, Status.YES)
    _login(client)
    resp = client.get(reverse("directory_availability"))
    assert resp.status_code == 200
    assert b"Anna Analyst" in resp.content
    assert b"Application Interviews" in resp.content


def test_availability_table_filter_only(client, analyst, interviews):
    analyst.public = True
    analyst.save()
    # available analyst
    services.set_availability(analyst, interviews, Status.YES)
    # a second analyst who is NOT available for interviews
    other = User.objects.create_user(
        email="bob@example.com", password="pw",
        first_name="Bob", last_name="Other",
    )
    other.profile.role = Profile.Role.ANALYST
    other.profile.public = True
    other.profile.save()
    services.set_availability(other.profile, interviews, Status.NO)

    _login(client)
    resp = client.get(reverse("directory_availability"), {"only": "application-interviews"})
    assert b"Anna Analyst" in resp.content
    assert b"Bob Other" not in resp.content


def test_availability_table_includes_opted_out_unlinked(client, analyst):
    # The members-only table lists every analyst (even directory opt-outs),
    # but a non-public analyst's name isn't a link (no public detail page).
    analyst.public = False
    analyst.save()
    _login(client)
    resp = client.get(reverse("directory_availability"))
    assert b"Anna Analyst" in resp.content
    slug = analyst.directory_slug
    assert f'/directory/{slug}/'.encode() not in resp.content


def test_detail_section_members_only(client, analyst, interviews):
    analyst.public = True
    analyst.save()
    services.set_availability(analyst, interviews, Status.YES)
    url = reverse("directory_detail", args=[analyst.directory_slug])

    # anonymous: no availability section
    anon = client.get(url)
    assert anon.status_code == 200
    assert b"Availability this year" not in anon.content

    # member: section shows
    _login(client)
    member = client.get(url)
    assert b"Availability this year" in member.content


def test_detail_section_absent_for_non_analyst(client):
    user = User.objects.create_user(
        email="cand@example.com", password="pw",
        first_name="Cara", last_name="Candidate",
    )
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.public = True
    user.profile.save()
    _login(client, email="viewer@example.com")
    resp = client.get(reverse("directory_detail", args=[user.profile.directory_slug]))
    assert resp.status_code == 200
    assert b"Availability this year" not in resp.content


# ---- Phase 3: self-service -----------------------------------------------


def test_self_update_sets_availability(client, analyst, interviews):
    advisor = AnalystFunction.objects.get(slug="advisor")
    client.force_login(analyst.user)
    resp = client.post(reverse("availability:self_update"), {
        f"fn_{interviews.pk}": Status.YES,
        f"fn_{advisor.pk}": Status.NO,
    })
    assert resp.status_code == 302
    span = AvailabilitySpan.objects.get(
        profile=analyst, function=interviews, end_date__isnull=True
    )
    assert span.status == Status.YES
    assert span.source == AvailabilitySpan.Source.SELF
    assert services.current_status(analyst, advisor) == Status.NO


def test_self_update_blocked_for_non_analyst(client):
    user = User.objects.create_user(email="cand2@example.com", password="pw")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()
    client.force_login(user)
    resp = client.post(reverse("availability:self_update"), {})
    assert resp.status_code == 403


def test_profile_editor_shows_availability_section_for_analyst(client, analyst):
    client.force_login(analyst.user)
    resp = client.get(reverse("profile_edit"))
    assert resp.status_code == 200
    assert b'id="availability"' in resp.content
