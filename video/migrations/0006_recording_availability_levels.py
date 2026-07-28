"""Recording availability levels (task #475).

Replaces the old five-value ladder with six settings spanning two independent
dimensions (registration and membership). ``members`` and ``public`` keep their
values; the other three are remapped:

    staff       -> owners   (same meaning: only the people who run the meeting)
    registrants -> roster   (an event's paid/comped registrants)
    group       -> roster   (Workgroup.is_member now covers both worlds)

Widening never happens here: every mapping is to an equal-or-narrower audience.
"""
from django.db import migrations, models

_MAP = {
    "staff": "owners",
    "registrants": "roster",
    "group": "roster",
}


def forwards(apps, schema_editor):
    Recording = apps.get_model("video", "Recording")
    for old, new in _MAP.items():
        Recording.objects.filter(listing_visibility=old).update(listing_visibility=new)
        Recording.objects.filter(content_visibility=old).update(content_visibility=new)


def backwards(apps, schema_editor):
    # "roster" was two distinct old values; collapse to the narrower of them so
    # a reverse migration can never widen an audience.
    Recording = apps.get_model("video", "Recording")
    Recording.objects.filter(listing_visibility="owners").update(listing_visibility="staff")
    Recording.objects.filter(content_visibility="owners").update(content_visibility="staff")
    for field in ("listing_visibility", "content_visibility"):
        Recording.objects.filter(**{field: "roster"}).update(**{field: "group"})
        Recording.objects.filter(**{field: "roster_members"}).update(**{field: "group"})
        Recording.objects.filter(**{field: "accounts"}).update(**{field: "members"})


class Migration(migrations.Migration):

    dependencies = [
        ('video', '0005_remove_dailyroom_video_room_exactly_one_owner_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='recording',
            name='content_visibility',
            field=models.CharField(choices=[('owners', 'Unavailable (owners only)'), ('roster_members', 'Registered group members who are LSP Members'), ('roster', 'Registered group members'), ('members', 'LSP Members'), ('accounts', 'LSP Members and Auditors'), ('public', 'Public')], default='owners', help_text='Who can watch it. Must be contained in the listing audience.', max_length=16),
        ),
        migrations.AlterField(
            model_name='recording',
            name='listing_visibility',
            field=models.CharField(choices=[('owners', 'Unavailable (owners only)'), ('roster_members', 'Registered group members who are LSP Members'), ('roster', 'Registered group members'), ('members', 'LSP Members'), ('accounts', 'LSP Members and Auditors'), ('public', 'Public')], default='owners', help_text='Who sees that this recording exists (e.g. on the event page).', max_length=16),
        ),
        migrations.RunPython(forwards, backwards),
    ]
