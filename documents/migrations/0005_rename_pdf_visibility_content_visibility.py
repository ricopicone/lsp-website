from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0004_document_owning_workgroup"),
    ]

    operations = [
        migrations.RenameField(
            model_name="document",
            old_name="pdf_visibility",
            new_name="content_visibility",
        ),
        migrations.AlterField(
            model_name="document",
            name="content_visibility",
            field=models.CharField(
                choices=[("public", "Public"), ("members", "Members only")],
                default="public",
                help_text=(
                    "Who can open the contents — the PDF. Cannot be more public "
                    "than the listing — e.g. listing=Members blocks Public contents."
                ),
                max_length=16,
            ),
        ),
    ]
