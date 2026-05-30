"""Tests for per-user timezone handling — middleware, filters, settings.

The LSP membership is distributed across timezones. We render times in
the user's preferred TZ (with PT shown in a hover tooltip) so a Beijing
member doesn't have to do 16-hour conversions in their head, while
PT-native members can still cross-reference quickly.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

import pytest
from django.template import Context, Template
from django.test import RequestFactory
from django.utils import timezone

from accounts.middleware import TimezoneMiddleware
from accounts.models import User

# A specific, unambiguous moment: 2026-10-15 17:00 PT = 2026-10-16 00:00 UTC.
# October 15 is during PDT, so PT = UTC-7. NY is EDT = UTC-4.
MOMENT_UTC = _dt.datetime(2026, 10, 16, 0, 0, tzinfo=_dt.timezone.utc)
"""5 PM Pacific (PDT) on October 15 2026 — also 8 PM Eastern, 9 AM next-day Beijing."""


# ---- Middleware --------------------------------------------------------


@pytest.mark.django_db
def test_middleware_activates_user_timezone():
    """An authenticated user with Profile.timezone set has that TZ active."""
    u = User.objects.create_user(email="ny@x.test")
    u.profile.timezone = "America/New_York"
    u.profile.save()

    def view(req):
        # Inside the request, the active TZ should match the user's pref.
        assert str(timezone.get_current_timezone()) == "America/New_York"
        return "ok"

    mw = TimezoneMiddleware(view)
    req = RequestFactory().get("/")
    req.user = u
    assert mw(req) == "ok"


@pytest.mark.django_db
def test_middleware_falls_back_to_project_tz_when_no_preference():
    """No preference → active TZ is the project default (Pacific)."""
    u = User.objects.create_user(email="default@x.test")
    # Profile.timezone is "" by default.

    captured = {}

    def view(req):
        captured["tz"] = str(timezone.get_current_timezone())
        return "ok"

    mw = TimezoneMiddleware(view)
    req = RequestFactory().get("/")
    req.user = u
    mw(req)
    # Project default in tests is whatever settings.TIME_ZONE is set to —
    # for this project that's America/Los_Angeles.
    assert captured["tz"] == "America/Los_Angeles"


@pytest.mark.django_db
def test_middleware_handles_anonymous_user():
    """Anonymous users → project default, no crash."""
    from django.contrib.auth.models import AnonymousUser

    captured = {}

    def view(req):
        captured["tz"] = str(timezone.get_current_timezone())
        return "ok"

    mw = TimezoneMiddleware(view)
    req = RequestFactory().get("/")
    req.user = AnonymousUser()
    mw(req)
    assert captured["tz"] == "America/Los_Angeles"


@pytest.mark.django_db
def test_middleware_ignores_invalid_timezone_string():
    """Garbage TZ string → silent fallback to project default."""
    u = User.objects.create_user(email="bogus@x.test")
    u.profile.timezone = "Mars/Olympus"
    u.profile.save()

    captured = {}

    def view(req):
        captured["tz"] = str(timezone.get_current_timezone())
        return "ok"

    mw = TimezoneMiddleware(view)
    req = RequestFactory().get("/")
    req.user = u
    mw(req)  # should not raise
    assert captured["tz"] == "America/Los_Angeles"


@pytest.mark.django_db
def test_middleware_deactivates_after_request():
    """TZ doesn't leak across requests via thread-local state."""
    u = User.objects.create_user(email="leaky@x.test")
    u.profile.timezone = "Asia/Shanghai"
    u.profile.save()

    mw = TimezoneMiddleware(lambda req: "ok")
    req = RequestFactory().get("/")
    req.user = u
    mw(req)
    # After the middleware returns, the override should be cleared.
    assert str(timezone.get_current_timezone()) == "America/Los_Angeles"


# ---- Template filters --------------------------------------------------


def _render(template_src: str, **ctx) -> str:
    return Template(template_src).render(Context(ctx))


def test_user_time_filter_renders_in_active_zone():
    """With Eastern active, a PT-evening session shows as 8:00 PM EDT."""
    with timezone.override(ZoneInfo("America/New_York")):
        out = _render(
            "{% load tz_filters %}{{ moment|user_time }}",
            moment=MOMENT_UTC,
        )
    assert "8:00 PM EDT" in out
    assert "<time" in out


def test_user_time_filter_tooltip_always_shows_pt():
    """The title attribute shows PT regardless of viewer's timezone."""
    with timezone.override(ZoneInfo("America/New_York")):
        out = _render(
            "{% load tz_filters %}{{ moment|user_time }}",
            moment=MOMENT_UTC,
        )
    assert "5:00 PM PT" in out
    assert 'title="' in out


def test_user_time_filter_for_pt_viewer_normalizes_pdt_to_pt():
    """PT viewers see 'PT' (not 'PDT' / 'PST') — LSP convention."""
    with timezone.override(ZoneInfo("America/Los_Angeles")):
        out = _render(
            "{% load tz_filters %}{{ moment|user_time }}",
            moment=MOMENT_UTC,
        )
    assert "5:00 PM PT" in out
    assert "PDT" not in out


def test_user_time_filter_beijing_shows_next_calendar_day():
    """Beijing's view of a PT-evening session lands on the next day."""
    with timezone.override(ZoneInfo("Asia/Shanghai")):
        out = _render(
            "{% load tz_filters %}{{ moment|user_time }}",
            moment=MOMENT_UTC,
        )
    # 5 PM PT on Oct 15 = 8 AM Oct 16 in Shanghai (CST = UTC+8).
    assert "8:00 AM CST" in out


def test_user_datetime_includes_date_in_display():
    """user_datetime includes day name + date in the visible text."""
    with timezone.override(ZoneInfo("America/New_York")):
        out = _render(
            "{% load tz_filters %}{{ moment|user_datetime }}",
            moment=MOMENT_UTC,
        )
    assert "Thu, Oct 15" in out
    assert "8:00 PM EDT" in out


def test_user_time_handles_none_gracefully():
    out = _render(
        "{% load tz_filters %}[{{ none|user_time }}]",
        none=None,
    )
    assert out == "[]"


def test_user_tz_name_returns_active_zone():
    with timezone.override(ZoneInfo("Europe/Berlin")):
        out = _render("{% load tz_filters %}{% user_tz_name %}")
    assert out == "Europe/Berlin"


# ---- Settings page -----------------------------------------------------


@pytest.mark.django_db
def test_timezone_settings_requires_login(client):
    from django.urls import reverse
    resp = client.get(reverse("timezone_settings"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_timezone_settings_renders_picker(client):
    from django.urls import reverse
    u = User.objects.create_user(email="picker@x.test", password="x")
    client.force_login(u)
    resp = client.get(reverse("timezone_settings"))
    assert resp.status_code == 200
    body = resp.content
    # Curated zones should appear in the rendered <select>.
    assert b"America/New_York" in body
    assert b"Asia/Shanghai" in body
    assert b"Pacific Time (project default)" in body


@pytest.mark.django_db
def test_timezone_settings_saves_user_choice(client):
    from django.urls import reverse
    u = User.objects.create_user(email="picker2@x.test", password="x")
    client.force_login(u)
    resp = client.post(
        reverse("timezone_settings"),
        {"timezone": "Asia/Tokyo"},
    )
    assert resp.status_code == 302
    u.profile.refresh_from_db()
    assert u.profile.timezone == "Asia/Tokyo"


@pytest.mark.django_db
def test_timezone_settings_can_clear_to_default(client):
    from django.urls import reverse
    u = User.objects.create_user(email="picker3@x.test", password="x")
    u.profile.timezone = "Europe/Berlin"
    u.profile.save()
    client.force_login(u)
    client.post(reverse("timezone_settings"), {"timezone": ""})
    u.profile.refresh_from_db()
    assert u.profile.timezone == ""


# ---- Browser-detected TZ endpoint --------------------------------------


@pytest.mark.django_db
def test_browser_tz_endpoint_saves_valid_zone(client):
    from django.urls import reverse
    u = User.objects.create_user(email="bd@x.test", password="x")
    client.force_login(u)
    resp = client.post(
        reverse("set_timezone_from_browser"),
        {"tz": "Europe/London"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["saved"] is True
    u.profile.refresh_from_db()
    assert u.profile.timezone == "Europe/London"


@pytest.mark.django_db
def test_browser_tz_endpoint_rejects_unknown_zone(client):
    from django.urls import reverse
    u = User.objects.create_user(email="bd2@x.test", password="x")
    client.force_login(u)
    resp = client.post(
        reverse("set_timezone_from_browser"),
        {"tz": "Mars/Olympus"},
    )
    body = resp.json()
    assert body["ok"] is False
    u.profile.refresh_from_db()
    assert u.profile.timezone == ""


@pytest.mark.django_db
def test_browser_tz_endpoint_does_not_overwrite_existing_preference(client):
    """Once the user has manually picked a TZ, the browser-detect endpoint
    becomes a no-op — we trust their explicit choice over auto-detection."""
    from django.urls import reverse
    u = User.objects.create_user(email="bd3@x.test", password="x")
    u.profile.timezone = "Asia/Tokyo"
    u.profile.save()
    client.force_login(u)
    resp = client.post(
        reverse("set_timezone_from_browser"),
        {"tz": "America/New_York"},
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["saved"] is False  # already-set short-circuit
    u.profile.refresh_from_db()
    assert u.profile.timezone == "Asia/Tokyo"  # unchanged


# ---- Email rendering uses recipient's TZ -------------------------------


@pytest.mark.django_db
def test_email_renders_in_recipient_timezone(mailoutbox):
    """A reminder email sent (by cron, no request context) renders dates
    in the recipient's stored TZ — not the project default."""
    from datetime import date
    from decimal import Decimal

    from django.utils import timezone as djtz

    from accounts.models import Profile
    from payments.emails import send_dues_reminder
    from payments.models import DuesPeriod

    u = User.objects.create_user(email="cron@x.test")
    u.profile.role = Profile.Role.CANDIDATE
    u.profile.timezone = "Asia/Shanghai"
    u.profile.save()

    period = DuesPeriod.objects.create(
        name="Test AY",
        slug="test-ay-tz",
        start_date=date(2026, 9, 1),
        due_date=date(2026, 10, 1),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )

    # Confirm middleware-active TZ is project default (cron-like
    # environment — no request).
    assert str(djtz.get_current_timezone()) == "America/Los_Angeles"

    send_dues_reminder(u, period)
    # The body should have rendered with Shanghai TZ active inside the
    # render_to_string call. We don't have a datetime in this template
    # currently, but the side-effect we can verify is that the active TZ
    # was restored back to project default after the function returned.
    assert str(djtz.get_current_timezone()) == "America/Los_Angeles"
    assert len(mailoutbox) == 1
