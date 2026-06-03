from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0006_alter_work_kind"),
    ]

    operations = [
        migrations.RenameField(
            model_name="work",
            old_name="pdf_visibility",
            new_name="content_visibility",
        ),
        migrations.AlterField(
            model_name="work",
            name="content_visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("members", "Members only"),
                    ("group", "Workgroup members only"),
                ],
                default="members",
                help_text=(
                    "Who can access the contents — the attached PDFs and the "
                    "published HTML body. Cannot be more public than the listing "
                    "— listing=Members blocks a Public contents setting."
                ),
                max_length=16,
            ),
        ),
    ]
