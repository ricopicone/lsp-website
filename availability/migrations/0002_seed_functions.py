"""Seed the four functions from the Applications Coordinator's yearly sheet.

Idempotent (get_or_create by slug) and reversible-as-a-no-op, so it's safe to
re-run and won't clobber edits the school later makes to names or ordering.
"""

from django.db import migrations

#: (slug, name, display_order) — verbatim column headers from the
#: "LSP Analysts Availability" sheet, in sheet order.
FUNCTIONS = [
    ("application-interviews", "Application Interviews", 1),
    ("advisor", "Advisor", 2),
    ("control-analysis", "Control analysis", 3),
    ("personal-analysis", "Personal analysis", 4),
]


def seed(apps, schema_editor):
    AnalystFunction = apps.get_model("availability", "AnalystFunction")
    for slug, name, order in FUNCTIONS:
        AnalystFunction.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "display_order": order},
        )


def unseed(apps, schema_editor):
    # Leave the rows in place on reverse — they may carry availability history.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
