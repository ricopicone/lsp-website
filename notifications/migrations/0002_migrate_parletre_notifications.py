"""Copy existing Parlêtre bell notifications into the new site-wide model.

Parlêtre originally owned its own ``Notification`` table (mention / reply /
new_thread). The site-wide notifications app supersedes it; this migration
carries the old rows forward (preserving read state and timestamps) so members
don't lose their bell history. The old ``parletre.Notification`` table is left
in place but dormant — nothing writes to it after this.
"""

from django.db import migrations

_VERB_TO_CATEGORY = {
    "mention": "parletre_mention",
    "reply": "parletre_reply",
    "new_thread": "parletre_thread",
}

_VERB_TITLE = {
    "mention": "mentioned you",
    "reply": "replied in your thread",
    "new_thread": "started a thread",
}


def _actor_name(user):
    if user is None:
        return "Someone"
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email or "Someone"


def _thread_url(thread):
    if thread is None or thread.channel is None:
        return ""
    return f"/parletre/{thread.channel.slug}/{thread.slug}/"


def forward(apps, schema_editor):
    OldNotification = apps.get_model("parletre", "Notification")
    Notification = apps.get_model("notifications", "Notification")
    ContentType = apps.get_model("contenttypes", "ContentType")

    post_ct = ContentType.objects.filter(app_label="parletre", model="post").first()
    thread_ct = ContentType.objects.filter(app_label="parletre", model="thread").first()

    # Preserve original timestamps: without this, auto_now_add stamps "now".
    created_field = Notification._meta.get_field("created_at")
    created_field.auto_now_add = False

    rows = []
    for old in OldNotification.objects.select_related(
        "actor", "thread", "thread__channel", "post", "post__thread", "post__thread__channel"
    ).all():
        verb = old.verb
        title = f"{_actor_name(old.actor)} {_VERB_TITLE.get(verb, 'posted')}"

        url = ""
        body = ""
        target_ct = target_id = None
        thread = old.thread
        post = old.post
        if thread is not None:
            body = thread.title
        if post is not None and post.thread_id:
            url = f"{_thread_url(post.thread)}#post-{post.id}"
            target_ct, target_id = post_ct, post.id
        elif thread is not None:
            body = thread.title
            url = _thread_url(thread)
            target_ct, target_id = thread_ct, thread.id

        rows.append(
            Notification(
                recipient_id=old.recipient_id,
                actor_id=old.actor_id,
                category=_VERB_TO_CATEGORY.get(verb, "parletre_mention"),
                title=title[:255],
                body=(body or "")[:512],
                url=url,
                target_type=target_ct,
                target_id=target_id,
                read_at=old.read_at,
                created_at=old.created_at,
            )
        )
    try:
        if rows:
            Notification.objects.bulk_create(rows, batch_size=500)
    finally:
        created_field.auto_now_add = True


def backward(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.filter(
        category__in=_VERB_TO_CATEGORY.values()
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
        ("parletre", "0018_the_gaze_no_recording"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
