from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("committees", "0006_foldin_committees"),
    ]

    operations = [
        migrations.DeleteModel(name="CommitteeMembership"),
    ]
