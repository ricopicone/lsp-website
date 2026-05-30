"""Drop the EXEMPT tuition-enrollment status.

Per LSP policy, students owe four total years of tuition before
transitioning out of in-training roles. "Skipping a year" is allowed
(the student pays regular event fees that year and the year doesn't
count toward the four); permanent exemption is not.

Any existing rows with status='exempt' are converted to 'skipping' so
no enrollment data is destroyed (treasurer can re-classify if needed).
Then the choices on the field are altered to remove EXEMPT.
"""

from django.db import migrations, models


def convert_exempt_to_skipping(apps, schema_editor):
    TuitionEnrollment = apps.get_model("payments", "TuitionEnrollment")
    TuitionEnrollment.objects.filter(status="exempt").update(status="skipping")


def noop_back(apps, schema_editor):
    # No automatic way to recover which rows had been EXEMPT — skip on reverse.
    pass


class Migration(migrations.Migration):
    dependencies = [("payments", "0008_reminder_cadence")]

    operations = [
        migrations.RunPython(convert_exempt_to_skipping, noop_back),
        migrations.AlterField(
            model_name="tuitionenrollment",
            name="status",
            field=models.CharField(
                choices=[
                    ("committed", "Committed (will pay)"),
                    ("payment_plan", "On payment plan"),
                    ("paid_in_full", "Paid in full"),
                    ("skipping", "Skipping this year"),
                ],
                max_length=20,
            ),
        ),
    ]
