import pytest
from django.contrib.auth import get_user_model

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
