"""A room invitation names one of three targets (task #694).

``room`` is *renamed*, not dropped and re-added: makemigrations does not detect
the rename non-interactively, and the remove-plus-add it generates instead would
silently discard every existing invitation's room.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0051_online_venue_help_text"),
        ("workgroups", "0025_meetingseries_timezone"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("video", "0009_alter_roominvitation_expires_at"),
    ]

    operations = [
        migrations.RenameField(
            model_name="roominvitation", old_name="room", new_name="personal_room",
        ),
        migrations.AlterField(
            model_name="roominvitation",
            name="personal_room",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="invitations", to="video.personalroom",
            ),
        ),
        migrations.AddField(
            model_name="roominvitation",
            name="workgroup",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="room_invitations", to="workgroups.workgroup",
            ),
        ),
        migrations.AddField(
            model_name="roominvitation",
            name="event",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="room_invitations", to="events.event",
            ),
        ),
        migrations.AddField(
            model_name="roominvitation",
            name="invited_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="issued_room_invitations", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="roominvitation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("event__isnull", True), ("personal_room__isnull", False),
                             ("workgroup__isnull", True)),
                    models.Q(("event__isnull", True), ("personal_room__isnull", True),
                             ("workgroup__isnull", False)),
                    models.Q(("event__isnull", False), ("personal_room__isnull", True),
                             ("workgroup__isnull", True)),
                    _connector="OR",
                ),
                name="video_invitation_exactly_one_target",
            ),
        ),
    ]
