"""Feature image on an event (task #504)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
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


# ---- Upload, replace, remove -------------------------------------------


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-img@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider-img@x.test")


def _post(client, event, **extra):
    data = {
        "upload": _upload(size=(2000, 1000)),
        "source": EventFeatureImage.Source.OWN_WORK,
        "rights_confirmed": "on",
    }
    data.update(extra)
    return client.post(reverse("events:feature_image", args=[event.slug]), data)


@pytest.mark.django_db
def test_faculty_can_upload_a_feature_image(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event, credit="René Magritte")

    img = event.feature()
    assert img is not None
    assert img.credit == "René Magritte"
    assert img.image_width and img.image_height
    assert img.original
    assert img.rights_confirmed_by == faculty
    assert img.rights_confirmed_at is not None


@pytest.mark.django_db
def test_the_rights_checkbox_is_required(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:feature_image", args=[event.slug]),
        {"upload": _upload(), "source": EventFeatureImage.Source.OWN_WORK},
    )
    assert response.status_code == 200
    assert event.feature() is None


@pytest.mark.django_db
def test_a_licensed_source_needs_a_url(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = _post(client, event, source=EventFeatureImage.Source.LICENSED)
    assert response.status_code == 200
    assert "source_url" in response.context["feature_image_form"].errors
    assert event.feature() is None


@pytest.mark.django_db
def test_metadata_can_be_edited_without_re_uploading(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    client.post(
        reverse("events:feature_image", args=[event.slug]),
        {"source": EventFeatureImage.Source.OWN_WORK,
         "rights_confirmed": "on", "credit": "Later credit"},
    )
    event.refresh_from_db()
    assert event.feature().credit == "Later credit"


@pytest.mark.django_db
def test_the_image_can_be_removed(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    client.post(reverse("events:feature_image", args=[event.slug]), {"remove": "1"})
    event.refresh_from_db()
    assert event.feature() is None


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_is_refused(
    client, event, outsider, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(outsider)
    assert _post(client, event).status_code == 403
    assert event.feature() is None


@pytest.mark.django_db
def test_a_too_small_image_is_reported_on_the_form(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = _post(client, event, upload=_upload(size=(400, 300)))
    assert response.status_code == 200
    assert "upload" in response.context["feature_image_form"].errors


@pytest.mark.django_db
def test_the_edit_page_offers_the_feature_image_form(client, event, faculty):
    client.force_login(faculty)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200
    assert "feature_image_form" in response.context
    assert reverse("events:feature_image", args=[event.slug]) in response.content.decode()


# ---- Rendering ---------------------------------------------------------
#
# A seminar's event page redirects to its Workspace, so the two render surfaces
# have to be exercised through two kinds of event: a standalone special event
# for the event page, the seminar for the Workspace masthead.


@pytest.fixture
def special_event(db):
    return Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 10, 3), end_date=date(2026, 10, 3),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def special_faculty(db, special_event):
    u = User.objects.create_user(email="fac-special@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    special_event.add_faculty(u)
    return u


@pytest.mark.django_db
def test_the_event_page_shows_the_image_and_its_credit(
    client, special_event, special_faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(special_faculty)
    _post(client, special_event, credit="René Magritte")
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert special_event.feature().image.url in body
    assert "René Magritte" in body


@pytest.mark.django_db
def test_the_alt_attribute_falls_back_to_the_title(
    client, special_event, special_faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(special_faculty)
    _post(client, special_event)
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert 'alt="Working with Masochism"' in body


@pytest.mark.django_db
def test_an_event_without_an_image_renders_no_figure(client, special_event):
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert "lsp-feature-image" not in body


@pytest.mark.django_db
def test_a_seminars_image_shows_on_its_workspace_masthead(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    body = client.get(event.workgroup.get_absolute_url()).content.decode()
    assert "lsp-feature-image" in body
    assert event.feature().image.url in body


# ---- Share preview -----------------------------------------------------


@pytest.mark.django_db
def test_the_event_page_carries_opengraph_tags_with_an_image(
    client, special_event, special_faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.SITE_BASE_URL = "https://lacanschool.org"
    client.force_login(special_faculty)
    _post(client, special_event)
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert 'property="og:title" content="Working with Masochism"' in body
    assert 'property="og:image"' in body
    assert 'name="twitter:card" content="summary_large_image"' in body
    assert "https://lacanschool.org/events/working-with-masochism/" in body


@pytest.mark.django_db
def test_an_event_without_an_image_still_carries_text_opengraph_tags(
    client, special_event, settings,
):
    settings.SITE_BASE_URL = "https://lacanschool.org"
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert 'property="og:title" content="Working with Masochism"' in body
    assert 'property="og:image"' not in body
    assert 'name="twitter:card" content="summary"' in body
