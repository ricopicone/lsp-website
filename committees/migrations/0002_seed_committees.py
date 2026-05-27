"""Seed the three core committees named in USR-7.

These are idempotent ``update_or_create`` calls keyed on slug, so the
migration is safe to re-run and won't clobber edits to existing rows.
"""

from django.db import migrations

SEED = [
    {
        "slug": "board",
        "name": "Board",
        "description": "Governance body; approves significant changes.",
        "charter": "",
        "public": False,
    },
    {
        "slug": "programming-committee",
        "name": "Programming Committee",
        "description": (
            "Runs seminars and special events; primary internal customer of "
            "the registration system."
        ),
        "charter": "",
        "public": False,
    },
    {
        "slug": "lsp-staff",
        "name": "LSP Staff",
        "description": "Administrative staff — Web Coordinator and Admin Assistant.",
        "charter": "",
        "public": False,
    },
]


def seed_committees(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    for row in SEED:
        Committee.objects.update_or_create(
            slug=row["slug"],
            defaults={k: v for k, v in row.items() if k != "slug"},
        )


def unseed_committees(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(slug__in=[row["slug"] for row in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0001_initial")]
    operations = [migrations.RunPython(seed_committees, unseed_committees)]
