from django.db import migrations, models


def copy_forward(apps, schema_editor):
    MeetingSeries = apps.get_model("workgroups", "MeetingSeries")
    for s in MeetingSeries.objects.all():
        s.week_positions = str(s.week_position)
        s.save(update_fields=["week_positions"])


def copy_back(apps, schema_editor):
    MeetingSeries = apps.get_model("workgroups", "MeetingSeries")
    for s in MeetingSeries.objects.all():
        first = (s.week_positions or "1").split(",")[0] or "1"
        s.week_position = int(first)
        s.save(update_fields=["week_position"])


class Migration(migrations.Migration):
    """Move MeetingSeries from a single week_position (int) to comma-coded
    week_positions (e.g. "1,3" = first & third weekday of the month)."""

    dependencies = [
        ("workgroups", "0019_workgroup_recording_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="meetingseries",
            name="week_positions",
            field=models.CharField(default="1", max_length=20),
        ),
        migrations.RunPython(copy_forward, copy_back),
        migrations.RemoveField(model_name="meetingseries", name="week_position"),
    ]
