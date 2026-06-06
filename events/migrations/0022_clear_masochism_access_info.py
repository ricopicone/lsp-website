from django.db import migrations


def clear_masochism_access_info(apps, schema_editor):
    """The "Working with Masochism" special event now meets in its own in-site
    Daily room, so its placeholder Zoom link in access_info is a footgun (the
    event page would show both a Join button and a stale link). Clear it. Any
    real venue/dial-in note can be re-entered in admin."""
    Event = apps.get_model("events", "Event")
    Event.objects.filter(title__icontains="masochism").exclude(
        access_info=""
    ).update(access_info="")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0021_event_recording_mode"),
    ]

    operations = [
        migrations.RunPython(clear_masochism_access_info, noop),
    ]
