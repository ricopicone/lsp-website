"""Move EventMemberSpeaker.bio_override → Profile.event_bio, then drop the field.

The bio-override-per-event design was replaced after one day of use with a
simpler "second bio on Profile" model. There is at most a handful of rows
to migrate (the field was minted yesterday).
"""

from django.db import migrations


def copy_overrides_to_profile(apps, schema_editor):
    EMS = apps.get_model("events", "EventMemberSpeaker")
    Profile = apps.get_model("accounts", "Profile")
    for ems in EMS.objects.exclude(bio_override="").select_related("user"):
        # If multiple events have overrides for the same user, the last write
        # wins — acceptable since there's only one production row right now.
        Profile.objects.filter(user=ems.user).update(event_bio=ems.bio_override)


def copy_back(apps, schema_editor):
    """No-op reverse: Profile.event_bio doesn't know which event(s) it came from."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0006_alter_event_speakers_eventmemberspeaker_and_more"),
        ("accounts", "0008_profile_event_bio_alter_profile_bio"),
    ]

    operations = [
        migrations.RunPython(copy_overrides_to_profile, copy_back),
        migrations.RemoveField(
            model_name="eventmemberspeaker",
            name="bio_override",
        ),
    ]
