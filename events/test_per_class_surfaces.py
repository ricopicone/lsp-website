"""Per-class billing as faculty and members see it (task #820, after #811)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse

from core.browser_forms import browser_form
from events import per_class
from events.models import ClassAttendance
from events.per_class_fixtures import enroll, make_event, make_session, make_tier, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def seminar():
    event = make_event(event_type="seminar")
    tier = make_tier(event)
    event.ensure_workgroup()
    faculty = make_user("fac@example.com")
    event.add_faculty(faculty)
    member = make_user("m@example.com")
    reg = enroll(member, event, tier)
    session = make_session(event, ends_ago=timedelta(hours=2))
    per_class.record_session(session)
    return event, faculty, reg, session


def test_marking_returns_to_the_class_just_corrected(client, seminar):
    """Saving collapsed the class back and left the message off-screen."""
    event, faculty, reg, session = seminar
    client.force_login(faculty)
    roster = event.workgroup.get_absolute_url() + "?tab=roster"
    html = client.get(roster).content.decode()
    assert f'id="class-{session.pk}"' in html

    att = ClassAttendance.objects.get(registration=reg)
    data = browser_form(html, action=reverse("events:attendance_mark", args=[att.pk]))
    response = client.post(reverse("events:attendance_mark", args=[att.pk]), data)

    assert response.status_code == 302
    assert response["Location"].endswith(f"#class-{session.pk}")
    att.refresh_from_db()
    assert att.present is False


def test_the_confirmation_page_reads_enrolled_not_paid(client, seminar):
    event, faculty, reg, session = seminar
    client.force_login(reg.user)
    html = client.get(reverse("registrations:confirm", args=[reg.pk])).content.decode()

    assert "Enrolled" in html
    assert "How priced" not in html  # nothing to say, so no empty row
    assert "Have a pricing code?" in html
    assert "convener" not in html.lower()
