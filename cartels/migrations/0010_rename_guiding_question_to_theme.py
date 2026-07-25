from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cartels", "0009_map_registration_status"),
    ]

    operations = [
        migrations.RenameField(
            model_name="cartel",
            old_name="guiding_question",
            new_name="theme",
        ),
        migrations.AlterField(
            model_name="cartel",
            name="theme",
            field=models.TextField(
                blank=True, help_text="The theme the cartel forms around."
            ),
        ),
    ]
