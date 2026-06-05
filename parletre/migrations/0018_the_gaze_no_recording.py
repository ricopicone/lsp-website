from django.db import migrations


def disable_gaze_recording(apps, schema_editor):
    """The Gaze is an open, all-member video room — turn off its Record button so
    no one can record the floating, anonymous comings-and-goings."""
    Channel = apps.get_model("parletre", "Channel")
    Channel.objects.filter(slug="the-gaze").update(recording_mode="off")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("parletre", "0017_channel_recording_mode"),
    ]

    operations = [
        migrations.RunPython(disable_gaze_recording, noop),
    ]
