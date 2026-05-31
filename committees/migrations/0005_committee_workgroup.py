import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("committees", "0004_alter_committeemembership_role_in_committee"),
        ("workgroups", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="committee",
            name="workgroup",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="committee",
                to="workgroups.workgroup",
                help_text="The backing workgroup (kind=committee) that holds the roster.",
            ),
        ),
    ]
