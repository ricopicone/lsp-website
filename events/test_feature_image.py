"""Feature image on an event (task #504)."""

from __future__ import annotations

from datetime import date

import pytest

from events.models import Event, EventFeatureImage


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.mark.django_db
def test_an_event_without_an_image_reports_none(event):
    assert event.feature() is None


@pytest.mark.django_db
def test_alt_text_falls_back_to_the_event_title(event):
    img = EventFeatureImage(event=event, source=EventFeatureImage.Source.OWN_WORK)
    assert img.alt_text == "Seminar XI"
    img.alt = "A pipe, captioned."
    assert img.alt_text == "A pipe, captioned."
