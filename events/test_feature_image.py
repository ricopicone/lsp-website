"""Feature image on an event (task #504)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from events import feature_images
from events.models import Event, EventFeatureImage


def _upload(size=(2000, 1000), name="art.png", mode="RGB", fmt="PNG"):
    colour = (10, 20, 30) if mode == "RGB" else (10, 20, 30, 255)
    img = Image.new(mode, size, colour)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


def _rendered(blob):
    return Image.open(io.BytesIO(blob.read()))


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


# ---- Pipeline (events/feature_images.py) ------------------------------


def test_a_wide_upload_is_clamped_to_the_widest_ratio():
    out = _rendered(feature_images.render(_upload(size=(3000, 600))))  # 5:1
    assert out.width / out.height == pytest.approx(feature_images.MAX_RATIO, abs=0.02)


def test_a_portrait_upload_is_clamped_to_square():
    out = _rendered(feature_images.render(_upload(size=(900, 2400))))
    assert out.width / out.height == pytest.approx(1.0, abs=0.02)


def test_an_in_range_upload_keeps_its_own_ratio():
    out = _rendered(feature_images.render(_upload(size=(1800, 1000))))  # 1.8:1
    assert out.width / out.height == pytest.approx(1.8, abs=0.02)


def test_the_render_is_bounded_webp():
    out = _rendered(feature_images.render(_upload(size=(4000, 2000))))
    assert out.format == "WEBP"
    assert out.width <= feature_images.RENDER_BOX[0]
    assert out.height <= feature_images.RENDER_BOX[1]


def test_a_crop_rect_is_honoured():
    crop = {"x": 0, "y": 0, "width": 1200, "height": 800}
    out = _rendered(feature_images.render(_upload(size=(2000, 1000)), crop))
    assert out.width / out.height == pytest.approx(1.5, abs=0.02)


def test_a_too_small_image_is_refused():
    with pytest.raises(feature_images.InvalidImage):
        feature_images.render(_upload(size=(400, 300)))


def test_an_unreadable_upload_is_refused():
    bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
    with pytest.raises(feature_images.InvalidImage):
        feature_images.render(bad)


def test_the_stored_original_is_bounded_webp():
    out = _rendered(feature_images.bound_original(_upload(size=(5000, 3000))))
    assert out.format == "WEBP"
    assert max(out.size) <= feature_images.ORIGINAL_BOX[0]
