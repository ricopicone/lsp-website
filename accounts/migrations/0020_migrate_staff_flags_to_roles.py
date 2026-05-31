"""Copy ``Profile.is_lsp_staff`` / ``is_cartel_coordinator`` onto StaffRole.

Behavior-preserving: every user who currently holds a flag becomes an explicit
holder of the matching ``core.StaffRole`` before the columns are dropped (next
migration). Reverse repopulates the flags from holdership.
"""

from __future__ import annotations

from django.db import migrations

PAIRS = [
    ("is_lsp_staff", "lsp_staff"),
    ("is_cartel_coordinator", "cartel_coordinator"),
]


def forwards(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    StaffRole = apps.get_model("core", "StaffRole")
    for field, key in PAIRS:
        role = StaffRole.objects.filter(key=key).first()
        if role is None:
            continue
        user_ids = Profile.objects.filter(**{field: True}).values_list(
            "user_id", flat=True
        )
        if user_ids:
            role.holders.add(*user_ids)


def backwards(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    StaffRole = apps.get_model("core", "StaffRole")
    for field, key in PAIRS:
        role = StaffRole.objects.filter(key=key).first()
        if role is None:
            continue
        for user_id in role.holders.values_list("id", flat=True):
            Profile.objects.filter(user_id=user_id).update(**{field: True})


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_profile_is_cartel_coordinator"),
        ("core", "0005_seed_lsp_and_cartel_roles"),
        # The fold-in writes Profile.is_lsp_staff via the historical model; it
        # must run before we copy holders across and drop the column, or its
        # historical state would see the column already gone.
        ("committees", "0006_foldin_committees"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
