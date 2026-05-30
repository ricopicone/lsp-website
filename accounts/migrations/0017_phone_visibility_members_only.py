from django.db import migrations


def phone_to_members(apps, schema_editor):
    """Phone now defaults to members-only. Flip existing profiles whose phone
    is still at the old 'public' default (carried from the Wix import) to
    members-only — but leave alone any that a member has already set to
    private. Members can restore Public from the editor."""
    Profile = apps.get_model("accounts", "Profile")
    for p in Profile.objects.all():
        fv = p.field_visibility or {}
        if fv.get("phone", "public") == "public":
            fv["phone"] = "members"
            p.field_visibility = fv
            p.save(update_fields=["field_visibility"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_profile_field_visibility_profile_public_phone_and_more"),
    ]

    operations = [
        migrations.RunPython(phone_to_members, migrations.RunPython.noop),
    ]
