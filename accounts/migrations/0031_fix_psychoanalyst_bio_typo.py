"""Fix the "psychoanalys" (missing t) typo in imported member bios.

Reported by Richard Reinhardt against Christopher Meyer's bio as shown on his
seminar pages (task #245). Word-boundary match so psychoanalysis/psychoanalytic
etc. are untouched; runs over every profile in case the Wix import carried the
same typo elsewhere.
"""

import re

from django.db import migrations

_TYPO = re.compile(r"\b([Pp]sychoanalys)\b")


def fix_bios(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    for profile in Profile.objects.exclude(bio="", event_bio=""):
        fields = []
        for field in ("bio", "event_bio"):
            text = getattr(profile, field)
            fixed = _TYPO.sub(r"\1t", text)
            if fixed != text:
                setattr(profile, field, fixed)
                fields.append(field)
        if fields:
            profile.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0030_memberintakesurvey_paid_all_tuition"),
    ]

    operations = [
        migrations.RunPython(fix_bios, migrations.RunPython.noop),
    ]
