"""Drop the cartel governance fields/models now copied onto the Workgroup layer
(see 0006). Runs only after the data migration."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cartels", "0006_move_to_generic"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="cartel",
            name="generator",
        ),
        migrations.RemoveField(
            model_name="cartel",
            name="review_note",
        ),
        migrations.RemoveField(
            model_name="cartel",
            name="reviewed_at",
        ),
        migrations.RemoveField(
            model_name="cartel",
            name="reviewed_by",
        ),
        migrations.RemoveField(
            model_name="cartel",
            name="status",
        ),
        migrations.DeleteModel(
            name="CartelInvitation",
        ),
        migrations.DeleteModel(
            name="CartelJoinRequest",
        ),
    ]
