from django.db import migrations


class Migration(migrations.Migration):
    """Rename SeminarProposal → EventProposal (it now handles seminars, reading
    groups, and special events). RenameModel preserves the table + all FK/M2M
    references and data."""

    dependencies = [
        ("events", "0024_seminarproposal_biography_seminarproposal_contact_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="SeminarProposal",
            new_name="EventProposal",
        ),
    ]
