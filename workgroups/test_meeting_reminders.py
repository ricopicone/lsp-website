"""Pre-meeting reminder feature: the ~15-min reminder with a personal,
meeting-scoped magic link, opt-out via notification settings, and the
per-group toggle."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import MagicLoginLink, User
from notifications.categories import Category, EmailDelivery
from notifications.models import Notification, NotificationPreference
from workgroups.models import Workgroup, WorkgroupMeeting, WorkgroupMembership

pytestmark = pytest.mark.django_db
UTC = datetime.timezone.utc


def _member(email):
    return User.objects.create_user(email=email, password="x", first_name="Mem")


def _group_with_member(email="m@x.test", **wg_kwargs):
    # Unique name/slug per call so two groups can coexist in one test.
    name = wg_kwargs.pop("name", f"Group {email}")
    slug = "g-" + email.replace("@", "-").replace(".", "-")
    wg = Workgroup.objects.create(
        kind=Workgroup.Kind.COMMITTEE, name=name, slug=slug,
        has_calendar=True, **wg_kwargs
    )
    u = _member(email)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, start_date=datetime.date(2026, 1, 1)
    )
    return wg, u


def _meeting(wg, *, minutes_ahead=10, **kwargs):
    return WorkgroupMeeting.objects.create(
        workgroup=wg,
        starts_at=timezone.now() + datetime.timedelta(minutes=minutes_ahead),
        **kwargs,
    )


# ---- MagicLoginLink window links -------------------------------------------

def test_create_for_window_is_multiuse_and_clamped():
    u = _member("w@x.test")
    far = timezone.now() + datetime.timedelta(hours=50)
    link = MagicLoginLink.create_for_window(u, expires_at=far)
    assert link.multi_use is True
    # Clamped to MAX_TTL (9h), not the 50h requested.
    cap = timezone.now() + MagicLoginLink.MAX_TTL + datetime.timedelta(minutes=1)
    assert link.expires_at <= cap
    # Reusable: still valid after a consume.
    assert link.is_valid
    link.consume()
    assert link.is_valid


def test_window_link_expires_at_window_end():
    u = _member("w2@x.test")
    past = timezone.now() - datetime.timedelta(minutes=1)
    link = MagicLoginLink.create_for_window(u, expires_at=past)
    assert not link.is_valid  # already past its window


# ---- The reminder command --------------------------------------------------

def test_reminder_sends_with_both_links_and_stamps(client, django_capture_on_commit_callbacks):
    wg, u = _group_with_member()
    m = _meeting(wg, title="Board sync")
    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_meeting_reminders")

    m.refresh_from_db()
    assert m.reminder_sent_at is not None
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    # Plain meet-tab link + a personal magic link.
    assert "?tab=meet" in body
    link = MagicLoginLink.objects.get(user=u)
    assert link.token in body
    assert "don't" in body.lower()  # the "don't share" warning

    # In-app bell row created too.
    assert Notification.objects.filter(
        recipient=u, category=Category.GROUP_MEETING_REMINDER
    ).exists()

    # The personal link signs in and lands on the Meet tab.
    consume = reverse("magic_link_consume", args=[link.token])
    resp = client.get(consume + f"?next={wg.get_absolute_url()}?tab=meet")
    assert resp.status_code == 302 and "tab=meet" in resp.url
    assert "_auth_user_id" in client.session


def test_reminder_is_idempotent_and_respects_window(django_capture_on_commit_callbacks):
    wg, _ = _group_with_member()
    _meeting(wg, minutes_ahead=10)
    _meeting(wg, minutes_ahead=120)  # outside the 15-min window

    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_meeting_reminders")
    assert len(mail.outbox) == 1  # only the in-window meeting

    with django_capture_on_commit_callbacks(execute=True):
        call_command("send_meeting_reminders")
    assert len(mail.outbox) == 1  # not re-sent


def test_reminder_skips_cancelled_and_toggled_off():
    wg_off, _ = _group_with_member("a@x.test", meeting_reminders=False)
    _meeting(wg_off)
    wg_on, _ = _group_with_member("b@x.test")
    _meeting(wg_on, cancelled=True)

    call_command("send_meeting_reminders")
    assert mail.outbox == []


def test_member_can_opt_out_of_reminder_email():
    wg, u = _group_with_member()
    pref = NotificationPreference.objects.create(user=u)
    pref.set(Category.GROUP_MEETING_REMINDER, in_app=True, email=EmailDelivery.OFF)
    pref.save()
    _meeting(wg)
    call_command("send_meeting_reminders")
    assert mail.outbox == []  # email suppressed by preference
    # Bell still fires.
    assert Notification.objects.filter(
        recipient=u, category=Category.GROUP_MEETING_REMINDER
    ).exists()
