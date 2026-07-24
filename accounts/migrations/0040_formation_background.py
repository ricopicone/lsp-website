from django.db import migrations, models


def copy_forward(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(clinical_background=True).update(
        formation_background="clinical")
    Profile.objects.filter(clinical_background=False).update(
        formation_background="unreviewed")


def copy_back(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(formation_background="clinical").update(
        clinical_background=True)
    Profile.objects.exclude(formation_background="clinical").update(
        clinical_background=False)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0039_announcementemail")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="formation_background",
            field=models.CharField(
                default="unreviewed", max_length=12,
                choices=[
                    ("unreviewed", "Not yet reviewed"),
                    ("clinical", "Clinical (one 4-year, one 2-year control analysis)"),
                    ("academic", "Academic (one 4-year, two 2-year control analyses)"),
                ],
                help_text="The student's professional background, which sets the "
                          "control-analysis requirement. Determined by the Meeting "
                          "of Analysts or the student's advisor. Independent of the "
                          "formation track.",
            ),
        ),
        migrations.RunPython(copy_forward, copy_back),
        migrations.RemoveField(model_name="profile", name="clinical_background"),
    ]
