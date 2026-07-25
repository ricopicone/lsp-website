"""Mark every pre-existing account as email-verified (task #471).

Signup verification arrives after ~80 imported members and a handful of real
self-signups already exist. Stamping them verified does two things: it keeps
anyone from being asked to confirm an address they have been using for months,
and it gives `purge_unverified_signups` an unambiguous signal — after this
migration, a null `email_verified_at` means "self-signup that never confirmed"
and nothing else, so the purge can never reach an admin-deactivated member.
"""

from django.db import migrations


def grandfather(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    for profile in Profile.objects.filter(email_verified_at__isnull=True).select_related("user"):
        profile.email_verified_at = profile.user.date_joined
        profile.save(update_fields=["email_verified_at"])


def unstamp(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.update(email_verified_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0041_profile_email_verified_at_emailverification"),
    ]

    operations = [
        migrations.RunPython(grandfather, unstamp),
    ]
