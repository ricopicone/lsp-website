"""Drop ``tuition_plan_review`` overrides that merely echo the old default.

The settings page writes an entry for *every* category whenever a member
saves, so a stored ``immediate`` is not evidence anyone chose it — and it
would beat the new Treasurer-aware default (task #491), leaving the whole
Board on the mail, which is exactly what they asked to stop. Removing those
entries restores "no override, use the role default"; a Board member who
genuinely wants the email sets it again on the settings page.

Deliberate non-default values (``off``, ``digest``) are left alone.
"""

from django.db import migrations

CATEGORY = "tuition_plan_review"
OLD_DEFAULT = "immediate"


def clear_incidental(apps, schema_editor):
    Preference = apps.get_model("notifications", "NotificationPreference")
    for pref in Preference.objects.all():
        overrides = pref.overrides or {}
        entry = overrides.get(CATEGORY)
        if isinstance(entry, dict) and entry.get("email") == OLD_DEFAULT:
            del overrides[CATEGORY]
            pref.overrides = overrides
            pref.save(update_fields=["overrides"])


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0013_alter_notification_category"),
    ]

    operations = [
        migrations.RunPython(clear_incidental, migrations.RunPython.noop),
    ]
