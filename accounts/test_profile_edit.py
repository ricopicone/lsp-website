"""Tests for the self-service profile editor (accounts.views.profile_edit),
the headshot square-crop pipeline (accounts.images), and the supporting
Profile fields/properties.
"""

from __future__ import annotations

import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.images import InvalidImage, render_headshot_square
from accounts.models import Profile, User


def _png_bytes(size=(120, 120), color=(10, 120, 200), halves=None) -> bytes:
    """A small PNG. ``halves`` paints left/right as (left_color, right_color)."""
    img = Image.new("RGB", size, color)
    if halves:
        left, right = halves
        for x in range(size[0]):
            for y in range(size[1]):
                img.putpixel((x, y), left if x < size[0] // 2 else right)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _upload(name="me.png", **kw) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _png_bytes(**kw), content_type="image/png")


# ---- Image pipeline ----------------------------------------------------


def test_render_headshot_square_outputs_512_webp():
    out = render_headshot_square(io.BytesIO(_png_bytes(size=(300, 150))))
    img = Image.open(io.BytesIO(out.read()))
    assert img.format == "WEBP"
    assert img.size == (512, 512)


def test_render_headshot_rejects_non_image():
    with pytest.raises(InvalidImage):
        render_headshot_square(io.BytesIO(b"this is definitely not an image"))


def test_render_headshot_honours_crop():
    # Left half red, right half blue; crop the top-left red square.
    src = io.BytesIO(_png_bytes(size=(100, 100), halves=((220, 20, 20), (20, 20, 220))))
    out = render_headshot_square(src, {"x": 0, "y": 0, "width": 50, "height": 50})
    img = Image.open(io.BytesIO(out.read())).convert("RGB")
    r, g, b = img.getpixel((256, 256))
    assert r > 180 and b < 70  # the cropped region is red, not blue


# ---- View: access + text fields ---------------------------------------


@pytest.mark.django_db
def test_profile_edit_requires_login(client):
    resp = client.get(reverse("profile_edit"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_profile_edit_saves_text_fields(client):
    u = User.objects.create_user(email="edit@x.test", password="x")
    client.force_login(u)
    resp = client.post(reverse("profile_edit"), {
        "first_name": "Jane",
        "last_name": "Doe",
        "display_name": "JD",
        "pronouns": "she/her",
        "bio": "Analyst and teacher.",
        "website": "https://example.org",
        "year_joined": "2018",
    })
    assert resp.status_code == 302
    u.refresh_from_db()
    u.profile.refresh_from_db()
    assert u.first_name == "Jane"
    assert u.profile.display_name == "JD"
    assert u.profile.pronouns == "she/her"
    assert u.profile.year_joined == 2018
    assert u.profile.academic_year_joined == "AY 2018–2019"
    assert u.profile.display_full_name == "JD"


@pytest.mark.django_db
def test_editor_renders_role_specific_sections(client, settings, tmp_path):
    """An analyst+faculty member sees listing, practice, billing, and the
    re-crop button (headshot_original present) — all template branches compile."""
    settings.MEDIA_ROOT = str(tmp_path)
    u = User.objects.create_user(email="fac@x.test", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = True
    u.profile.headshot_original.save("o.png", SimpleUploadedFile("o.png", _png_bytes()))
    u.profile.save()
    client.force_login(u)
    body = client.get(reverse("profile_edit")).content
    assert b"Your public profile" in body
    assert b"Practice" in body
    assert b"accepting new analysands" in body
    assert b"Default billing for new seminars" in body
    assert b"Re-center / zoom" in body


@pytest.mark.django_db
def test_modalities_roundtrip(client):
    u = User.objects.create_user(email="mods@x.test", password="x")
    client.force_login(u)
    client.post(reverse("profile_edit"), {
        "consultation_modalities": ["in_person", "video"],
    })
    u.profile.refresh_from_db()
    assert u.profile.consultation_modalities == "in_person,video"
    assert u.profile.modalities_list == ["in_person", "video"]
    assert "In person" in u.profile.modalities_display


@pytest.mark.django_db
def test_role_and_is_faculty_are_not_user_editable(client):
    u = User.objects.create_user(email="standing@x.test", password="x")
    assert u.profile.role == Profile.Role.EXTERNAL
    client.force_login(u)
    # Attempt to escalate standing via the form — must be ignored.
    client.post(reverse("profile_edit"), {
        "role": Profile.Role.ANALYST,
        "is_faculty": "on",
        "bio": "hi",
    })
    u.profile.refresh_from_db()
    assert u.profile.role == Profile.Role.EXTERNAL
    assert u.profile.is_faculty is False


# ---- View: geocode staling --------------------------------------------


@pytest.mark.django_db
def test_location_change_stales_geocode(client):
    u = User.objects.create_user(email="loc@x.test", password="x")
    u.profile.location = "Los Gatos, CA"
    u.profile.location_lat = 37.2
    u.profile.location_lng = -121.9
    u.profile.location_pins = [{"lat": 37.2, "lng": -121.9, "label": "Los Gatos, CA"}]
    u.profile.save()
    client.force_login(u)
    client.post(reverse("profile_edit"), {"location": "Berlin, Germany"})
    u.profile.refresh_from_db()
    assert u.profile.location == "Berlin, Germany"
    assert u.profile.location_lat is None
    assert u.profile.location_lng is None
    assert u.profile.location_pins == []


@pytest.mark.django_db
def test_location_unchanged_keeps_geocode(client):
    u = User.objects.create_user(email="loc2@x.test", password="x")
    u.profile.location = "Los Gatos, CA"
    u.profile.location_lat = 37.2
    u.profile.location_lng = -121.9
    u.profile.save()
    client.force_login(u)
    client.post(reverse("profile_edit"), {"location": "Los Gatos, CA"})
    u.profile.refresh_from_db()
    assert u.profile.location_lat == 37.2


# ---- View: headshot pipeline ------------------------------------------


@pytest.mark.django_db
def test_headshot_upload_creates_square(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    u = User.objects.create_user(email="pic@x.test", password="x")
    client.force_login(u)
    crop = json.dumps({"x": 0, "y": 0, "width": 80, "height": 80})
    resp = client.post(reverse("profile_edit"), {
        "headshot_file": _upload(size=(200, 200)),
        "headshot_crop": crop,
    })
    assert resp.status_code == 302
    u.profile.refresh_from_db()
    assert u.profile.headshot
    assert u.profile.headshot_original  # original retained for re-cropping
    assert u.profile.headshot_crop.get("width") == 80
    img = Image.open(u.profile.headshot.path)
    assert img.format == "WEBP"
    assert img.size == (512, 512)


@pytest.mark.django_db
def test_bad_headshot_blocks_save(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    u = User.objects.create_user(email="badpic@x.test", password="x")
    client.force_login(u)
    bad = SimpleUploadedFile("x.png", b"nope not an image", content_type="image/png")
    resp = client.post(reverse("profile_edit"), {
        "bio": "should not persist",
        "headshot_file": bad,
    })
    # Re-renders the form (200) with an error; nothing saved.
    assert resp.status_code == 200
    u.profile.refresh_from_db()
    assert not u.profile.headshot
    assert u.profile.bio == ""


@pytest.mark.django_db
def test_remove_headshot(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    u = User.objects.create_user(email="rm@x.test", password="x")
    # Seed a headshot via the pipeline.
    square = render_headshot_square(io.BytesIO(_png_bytes()))
    u.profile.headshot.save("seed.webp", square, save=True)
    assert u.profile.headshot
    client.force_login(u)
    resp = client.post(reverse("profile_edit"), {"remove_headshot": "1"})
    assert resp.status_code == 302
    u.profile.refresh_from_db()
    assert not u.profile.headshot
