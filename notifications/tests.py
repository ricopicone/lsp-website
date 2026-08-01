from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.categories import Category, EmailDelivery
from notifications.dispatch import notify
from notifications.models import Notification, NotificationPreference
from notifications.preferences import resolve

User = get_user_model()


def make_user(email="u@x.co", **kw):
    return User.objects.create_user(email=email, password="x", **kw)


@pytest.mark.django_db
def test_notify_creates_in_app_row_and_emails(mailoutbox, django_capture_on_commit_callbacks):
    user = make_user()
    with django_capture_on_commit_callbacks(execute=True):
        n = notify(
            user, Category.REGISTRATION_STATUS,
            title="Your registration was approved",
            body="Working with Masochism", url="/events/x/",
        )
    assert n is not None
    assert n.category == Category.REGISTRATION_STATUS
    assert Notification.objects.filter(recipient=user, read_at__isnull=True).count() == 1
    assert len(mailoutbox) == 1  # default email on for this category


@pytest.mark.django_db
def test_email_off_preference_suppresses_email_but_keeps_in_app(
    mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user()
    pref = NotificationPreference.objects.create(user=user)
    pref.set(Category.REGISTRATION_STATUS, in_app=True, email=EmailDelivery.OFF)
    pref.save()
    with django_capture_on_commit_callbacks(execute=True):
        notify(user, Category.REGISTRATION_STATUS, title="Update", url="/x/")
    assert Notification.objects.filter(recipient=user).count() == 1
    assert mailoutbox == []


@pytest.mark.django_db
def test_locked_category_emails_despite_preference(mailoutbox, django_capture_on_commit_callbacks):
    user = make_user()
    pref = NotificationPreference.objects.create(user=user)
    # Try to silence a transactional category — must be ignored.
    pref.set(Category.PAYMENT_RECEIPT, in_app=False, email=EmailDelivery.OFF)
    pref.save()
    res = resolve(user, Category.PAYMENT_RECEIPT)
    assert res.email is True
    assert res.email_editable is False
    sent = {"n": 0}

    def _send():
        sent["n"] += 1

    with django_capture_on_commit_callbacks(execute=True):
        notify(user, Category.PAYMENT_RECEIPT, title="Receipt", email_fn=_send)
    assert sent["n"] == 1  # locked → email_fn invoked regardless of pref


@pytest.mark.django_db
def test_email_false_suppresses_email(mailoutbox, django_capture_on_commit_callbacks):
    """Parlêtre passes email=False because it sends its own email."""
    user = make_user()
    with django_capture_on_commit_callbacks(execute=True):
        notify(user, Category.PARLETRE_MENTION, title="x mentioned you", email=False)
    assert Notification.objects.filter(recipient=user).count() == 1
    assert mailoutbox == []


@pytest.mark.django_db
def test_account_security_is_email_only(mailoutbox, django_capture_on_commit_callbacks):
    user = make_user()
    res = resolve(user, Category.ACCOUNT_SECURITY)
    assert res.in_app is False and res.email is True
    with django_capture_on_commit_callbacks(execute=True):
        n = notify(user, Category.ACCOUNT_SECURITY, title="Sign-in link")
    # no in-app row, but it returns None and still emails
    assert n is None
    assert Notification.objects.filter(recipient=user).count() == 0
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_dedupe_skips_unread_duplicate():
    user = make_user()
    actor = make_user("a@x.co")
    notify(user, Category.GROUP_MEMBERSHIP, title="Added to Cartel A",
           actor=actor, target=actor, dedupe=True, email=False)
    notify(user, Category.GROUP_MEMBERSHIP, title="Added to Cartel A",
           actor=actor, target=actor, dedupe=True, email=False)
    assert Notification.objects.filter(recipient=user).count() == 1


@pytest.mark.django_db
def test_feed_and_mark_all_read(client):
    user = make_user()
    Notification.objects.create(recipient=user, category=Category.REGISTRATION_STATUS, title="A")
    Notification.objects.create(recipient=user, category=Category.REGISTRATION_STATUS, title="B")
    client.force_login(user)
    resp = client.get("/notifications/")
    assert resp.status_code == 200
    assert resp.context["unread"] == 2
    client.post("/notifications/read-all/")
    assert Notification.objects.filter(recipient=user, read_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_group_decision_notifies_members_except_actor():
    from workgroups import notifications as notify_groups
    from workgroups.models import Workgroup, WorkgroupDecision

    wg = Workgroup.objects.create(name="Cartel A", kind=Workgroup.Kind.CARTEL)
    actor = make_user("lead@x.co")
    member = make_user("m@x.co")
    wg.add_member(actor)
    wg.add_member(member)

    decision = WorkgroupDecision.objects.create(
        workgroup=wg, created_by=actor, title="Meet weekly",
    )
    notify_groups.decision_recorded(decision, actor=actor)

    assert Notification.objects.filter(
        recipient=member, category=Category.GROUP_DECISION
    ).count() == 1
    # the actor is not notified about their own action
    assert not Notification.objects.filter(recipient=actor).exists()


@pytest.mark.django_db
def test_group_membership_notifies_added_user(mailoutbox):
    from workgroups import notifications as notify_groups
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(name="Working Group B", kind=Workgroup.Kind.WORKING_GROUP)
    user = make_user("added@x.co")
    notify_groups.member_added(wg, user)
    n = Notification.objects.get(recipient=user, category=Category.GROUP_MEMBERSHIP)
    assert wg.name in n.title
    # GROUP_* categories default to email-off, so no email is sent.
    assert mailoutbox == []


@pytest.mark.django_db
def test_recent_panel_and_mark_read(client):
    user = make_user()
    n = Notification.objects.create(
        recipient=user, category=Category.REGISTRATION_STATUS, title="A", url="/x/"
    )
    client.force_login(user)
    resp = client.get("/notifications/recent/")
    assert resp.status_code == 200
    assert b"A" in resp.content
    # the async per-item mark-read endpoint returns 204 and clears unread
    resp = client.post(f"/notifications/{n.pk}/seen/")
    assert resp.status_code == 204
    n.refresh_from_db()
    assert not n.is_unread


@pytest.mark.django_db(transaction=True)
def test_bell_consumer_receives_live_push():
    from asgiref.sync import async_to_sync
    from channels.db import database_sync_to_async
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator

    from notifications.realtime import broadcast_to_user
    from notifications.routing import websocket_urlpatterns

    user = make_user("live@x.co")

    async def scenario():
        comm = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), "/ws/notifications/"
        )
        comm.scope["user"] = user
        connected, _ = await comm.connect()
        assert connected
        first = await comm.receive_json_from()   # initial count on connect
        assert first["unread"] == 0
        # a server-side broadcast reaches the open socket
        await database_sync_to_async(broadcast_to_user)(
            user.id, unread=3, item={"title": "Hi"}
        )
        live = await comm.receive_json_from()
        assert live["unread"] == 3
        assert live["item"]["title"] == "Hi"
        await comm.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_digest_preference_holds_email_and_flags_row(
    mailoutbox, django_capture_on_commit_callbacks
):
    user = make_user()
    pref = NotificationPreference.objects.create(user=user)
    pref.set(Category.REGISTRATION_STATUS, in_app=True, email=EmailDelivery.DIGEST)
    pref.save()
    with django_capture_on_commit_callbacks(execute=True):
        n = notify(user, Category.REGISTRATION_STATUS, title="Held for digest")
    assert n.digest_pending is True
    assert mailoutbox == []  # no immediate email — it waits for the digest


@pytest.mark.django_db
def test_send_notification_digests_batches_and_clears(mailoutbox):
    from django.core.management import call_command

    user = make_user()
    pref = NotificationPreference.objects.create(
        user=user, digest_cadence="weekly"
    )
    pref.set(Category.REGISTRATION_STATUS, in_app=True, email=EmailDelivery.DIGEST)
    pref.save()
    Notification.objects.create(
        recipient=user, category=Category.REGISTRATION_STATUS,
        title="One", url="/a/", digest_pending=True,
    )
    Notification.objects.create(
        recipient=user, category=Category.GROUP_DECISION,
        title="Two", url="/b/", digest_pending=True,
    )

    call_command("send_notification_digests")

    assert len(mailoutbox) == 1
    assert "One" in mailoutbox[0].body and "Two" in mailoutbox[0].body
    # held rows are cleared so a second run sends nothing
    assert Notification.objects.filter(recipient=user, digest_pending=True).count() == 0
    mailoutbox.clear()
    call_command("send_notification_digests")
    assert mailoutbox == []


@pytest.mark.django_db
def test_digest_not_due_before_cadence_elapses():
    from notifications import digests

    user = make_user()
    now = timezone.now()
    pref = NotificationPreference.objects.create(
        user=user, digest_cadence="weekly", last_digest_at=now,
    )
    assert digests.is_due(pref, now) is False
    pref.digest_cadence = "daily"
    assert digests.is_due(pref, now) is False
    pref.last_digest_at = now - timedelta(days=2)
    assert digests.is_due(pref, now) is True


@pytest.mark.django_db
def test_settings_saves_preferences(client):
    user = make_user()
    client.force_login(user)
    # turn off email for dues reminders, leave in-app on
    resp = client.post("/notifications/settings/", {
        f"{Category.DUES_REMINDER}__in_app": "on",
        # no email key => off
    })
    assert resp.status_code == 302
    res = resolve(user, Category.DUES_REMINDER)
    assert res.in_app is True and res.email is False


@pytest.mark.django_db
def test_settings_digest_forces_in_app_on(client):
    """Choosing 'digest' email keeps the in-app channel on even if its toggle
    wasn't submitted (a digest is held in the bell row)."""
    user = make_user()
    client.force_login(user)
    resp = client.post("/notifications/settings/", {
        f"{Category.DUES_REMINDER}__email": "digest",
        # deliberately omit the in_app toggle
    })
    assert resp.status_code == 302
    res = resolve(user, Category.DUES_REMINDER)
    assert res.in_app is True
    assert res.email_mode == EmailDelivery.DIGEST


@pytest.mark.django_db
def test_default_email_for_gives_each_recipient_its_own_default(monkeypatch):
    from notifications import categories as cats

    meta = cats.CategoryMeta(
        cats.SECTION_ACCOUNT, "Test queue",
        default_email_for=lambda u: (
            EmailDelivery.IMMEDIATE if u.email == "owner@x.co" else EmailDelivery.OFF
        ),
    )
    monkeypatch.setitem(cats.CATEGORY_META, "test_queue", meta)

    owner = make_user("owner@x.co")
    bystander = make_user("bystander@x.co")

    assert resolve(owner, "test_queue").email is True
    assert resolve(bystander, "test_queue").email is False
    # The bell is unaffected — only email delivery varies by recipient.
    assert resolve(bystander, "test_queue").in_app is True


@pytest.mark.django_db
def test_explicit_override_beats_the_role_default(monkeypatch):
    from notifications import categories as cats

    meta = cats.CategoryMeta(
        cats.SECTION_ACCOUNT, "Test queue",
        default_email_for=lambda u: EmailDelivery.OFF,
    )
    monkeypatch.setitem(cats.CATEGORY_META, "test_queue", meta)

    user = make_user("opted-in@x.co")
    pref = NotificationPreference.objects.create(user=user)
    pref.set("test_queue", in_app=True, email=EmailDelivery.IMMEDIATE)
    pref.save()

    user = User.objects.get(pk=user.pk)  # drop the cached relation
    assert resolve(user, "test_queue").email is True


@pytest.mark.django_db
def test_categories_without_a_role_default_are_unchanged():
    user = make_user("plain@x.co")
    assert resolve(user, Category.REGISTRATION_STATUS).email is True


@pytest.mark.django_db
def test_incidental_plan_review_override_is_cleared_by_the_migration():
    """The settings page stores an entry for every category on save, so a
    stored `immediate` is not evidence the member chose it (task #491)."""
    from importlib import import_module

    from django.apps import apps as django_apps

    mod = import_module(
        "notifications.migrations.0014_clear_incidental_plan_review_overrides"
    )

    incidental = make_user("incidental@x.co")
    NotificationPreference.objects.create(
        user=incidental,
        overrides={
            "tuition_plan_review": {"in_app": True, "email": "immediate"},
            "dues_reminder": {"in_app": True, "email": "immediate"},
        },
    )
    deliberate = make_user("deliberate@x.co")
    NotificationPreference.objects.create(
        user=deliberate,
        overrides={"tuition_plan_review": {"in_app": True, "email": "off"}},
    )

    mod.clear_incidental(django_apps, None)

    assert "tuition_plan_review" not in NotificationPreference.objects.get(
        user=incidental
    ).overrides
    # Unrelated categories are untouched.
    assert "dues_reminder" in NotificationPreference.objects.get(
        user=incidental
    ).overrides
    # A deliberate "off" is a real choice — leave it.
    assert NotificationPreference.objects.get(user=deliberate).overrides[
        "tuition_plan_review"
    ]["email"] == "off"
