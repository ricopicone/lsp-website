"""An event page links its faculty, conveners and member speakers to their
directory pages, when they have one (task #820)."""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


def _person(email, first, last, *, public=True):
    u = User.objects.create_user(email=email, first_name=first, last_name=last)
    u.profile.role = Profile.Role.ANALYST
    u.profile.public = public
    u.profile.save()
    return u


def _page(client, event):
    return client.get(
        reverse("events:detail", args=[event.slug]), follow=True,
    ).content.decode()


def test_listed_faculty_link_to_their_directory_page(client):
    e = Event.objects.create(
        title="Seminar", slug="sem", start_date=date(2030, 9, 1),
        end_date=date(2030, 12, 1), published=True, status=Event.Status.OPEN,
    )
    jane = _person("jane@x.test", "Jane", "Doe")
    hidden = _person("hid@x.test", "Hidden", "Person", public=False)
    e.add_faculty(jane)
    e.add_faculty(hidden)
    body = _page(client, e)
    assert reverse("directory_detail", args=["jane-doe"]) in body
    # Not in the directory: named, but no link to a page that would 404.
    assert "Hidden Person" in body
    assert reverse("directory_detail", args=["hidden-person"]) not in body


def test_reading_group_lists_and_links_its_conveners(client):
    rg = Event.objects.create(
        title="Reading Group", slug="rg", event_type=Event.Type.READING_GROUP,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
        published=True, status=Event.Status.OPEN,
    )
    rg.ensure_workgroup()
    ann = _person("ann@x.test", "Ann", "Convener")
    WorkgroupMembership.objects.create(
        workgroup=rg.workgroup, user=ann,
        role=WorkgroupMembership.Role.ORGANIZER, start_date=timezone.localdate(),
    )
    body = _page(client, rg)
    assert "Organizers" in body
    assert reverse("directory_detail", args=["ann-convener"]) in body


def test_member_speaker_links_to_their_directory_page(client):
    e = Event.objects.create(
        title="Special", slug="special", event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 1), end_date=date(2030, 9, 1),
        published=True, status=Event.Status.OPEN,
    )
    e.member_speakers.add(_person("sp@x.test", "Sam", "Speaker"))
    assert reverse("directory_detail", args=["sam-speaker"]) in _page(client, e)
