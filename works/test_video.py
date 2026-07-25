"""Works video: upload controls (enable + size cap), gated playback, and the
web-developer control surface."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from works.forms import WorkForm
from works.models import VideoUploadSettings, Work

pytestmark = pytest.mark.django_db


def _user(email="m@x.test", role=Profile.Role.MEMBER):
    u = User.objects.create_user(email=email, password="x", first_name="M", last_name="X")
    u.profile.role = role
    u.profile.save()
    return u


def _video(name="clip.mp4", size_bytes=1024, ctype="video/mp4"):
    return SimpleUploadedFile(name, b"\x00" * size_bytes, content_type=ctype)


def _form_data(**over):
    data = {
        "title": "AV piece", "kind": Work.Kind.PALIMPSEST,
        "listing_visibility": Work.Visibility.MEMBERS,
        "content_visibility": Work.Visibility.MEMBERS,
        "lsp_authors": "",
    }
    data.update(over)
    return data


# ---- settings singleton ----------------------------------------------------

def test_settings_defaults():
    cfg = VideoUploadSettings.load()
    assert cfg.enabled is True
    assert cfg.max_file_mb == 1024
    assert cfg.max_file_bytes == 1024 * 1024 * 1024


# ---- upload validation -----------------------------------------------------

def test_valid_video_uploads():
    u = _user()
    form = WorkForm(_form_data(), {"video": _video()}, current_user=u)
    assert form.is_valid(), form.errors
    work = form.save()
    assert work.video


def test_rejects_when_disabled():
    cfg = VideoUploadSettings.load()
    cfg.enabled = False
    cfg.save()
    u = _user()
    form = WorkForm(_form_data(), {"video": _video()}, current_user=u)
    assert not form.is_valid()
    assert "video" in form.errors


def test_rejects_oversize():
    cfg = VideoUploadSettings.load()
    cfg.max_file_mb = 1  # 1 MB cap
    cfg.save()
    u = _user()
    big = _video(size_bytes=2 * 1024 * 1024)  # 2 MB
    form = WorkForm(_form_data(), {"video": big}, current_user=u)
    assert not form.is_valid()
    assert "video" in form.errors


def test_rejects_non_video_extension():
    u = _user()
    form = WorkForm(_form_data(), {"video": _video(name="notvideo.exe")}, current_user=u)
    assert not form.is_valid()
    assert "video" in form.errors


# ---- gated playback --------------------------------------------------------

def test_video_view_gated_by_content_visibility(client):
    owner = _user("owner@x.test")
    Work.objects.create(
        title="V", slug="v", kind=Work.Kind.PALIMPSEST,
        listing_visibility=Work.Visibility.PUBLIC,
        content_visibility=Work.Visibility.MEMBERS,
        video=_video(), submitted_by=owner,
    )
    # Anonymous → bounced to login (returned to the video after sign-in).
    url = reverse("works:video", args=["v"])
    anon = client.get(url)
    assert anon.status_code == 302
    assert anon.url == f"/accounts/login/?next={url}"
    # Member → served (dev: FileResponse, no private bucket to presign).
    client.force_login(_user("member@x.test"))
    resp = client.get(reverse("works:video", args=["v"]))
    assert resp.status_code in (200, 302)


# ---- dev control surface ---------------------------------------------------

def test_video_settings_page_requires_web_developer(client):
    plain = _user("plain@x.test")
    client.force_login(plain)
    assert client.get(reverse("video_upload_settings")).status_code in (302, 403, 404)


# ---- direct-to-S3 upload ---------------------------------------------------

import json  # noqa: E402


def test_presign_requires_member(client):
    # Anonymous → login redirect.
    assert client.post(reverse("works:video_presign")).status_code == 302
    # Logged in but not an LSP member → 404.
    client.force_login(_user("ext@x.test", role=Profile.Role.EXTERNAL))
    assert client.post(
        reverse("works:video_presign"),
        data=json.dumps({"filename": "x.mp4", "content_type": "video/mp4"}),
        content_type="application/json",
    ).status_code == 404


def test_presign_falls_back_without_bucket(client):
    """In dev/test there's no private bucket, so the endpoint tells the client
    to fall back to a server-side upload."""
    client.force_login(_user())
    resp = client.post(
        reverse("works:video_presign"),
        data=json.dumps({"filename": "x.mp4", "content_type": "video/mp4"}),
        content_type="application/json",
    )
    assert resp.status_code == 200 and resp.json().get("fallback") is True


def test_presign_rejects_non_video(client):
    client.force_login(_user())
    resp = client.post(
        reverse("works:video_presign"),
        data=json.dumps({"filename": "x.exe", "content_type": "application/octet-stream"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_presign_blocked_when_disabled(client):
    cfg = VideoUploadSettings.load()
    cfg.enabled = False
    cfg.save()
    client.force_login(_user())
    resp = client.post(
        reverse("works:video_presign"),
        data=json.dumps({"filename": "x.mp4", "content_type": "video/mp4"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_form_attaches_via_video_key(monkeypatch):
    """A verified incoming/ upload is promoted (S3 copy) and attached, with no
    file passing through the app server."""
    import core.storage as storage

    monkeypatch.setattr(storage, "head_private_object",
                        lambda key: {"size": 1024, "content_type": "video/mp4"})
    copied = {}
    def _copy(src, dest):
        copied["src"], copied["dest"] = src, dest
        return True
    monkeypatch.setattr(storage, "copy_private_object", _copy)

    u = _user()
    key = "works/videos/incoming/abc123.mp4"
    form = WorkForm(_form_data(video_key=key), current_user=u)
    assert form.is_valid(), form.errors
    work = form.save()
    assert copied["src"] == key
    assert work.video.name == copied["dest"]
    assert work.video.name.startswith("works/videos/") and "incoming" not in work.video.name


def test_form_rejects_video_key_outside_prefix(monkeypatch):
    import core.storage as storage
    monkeypatch.setattr(storage, "head_private_object",
                        lambda key: {"size": 1, "content_type": "video/mp4"})
    u = _user()
    form = WorkForm(_form_data(video_key="evil/secret.mp4"), current_user=u)
    assert not form.is_valid()
    assert "video_key" in form.errors


def test_web_developer_can_change_settings(client):
    dev = _user("dev@x.test")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_DEVELOPER, defaults={"name": "Web Developer"}
    )
    role.holders.add(dev)
    client.force_login(dev)
    resp = client.post(reverse("video_upload_settings"),
                       {"enabled": "", "max_file_mb": "500"})
    assert resp.status_code == 200
    cfg = VideoUploadSettings.load()
    assert cfg.enabled is False
    assert cfg.max_file_mb == 500
