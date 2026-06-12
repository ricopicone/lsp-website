"""Seed the referral message templates from the coordinator's wording.

The wording lives in ``referrals.seed_templates`` (verbatim from Diana
Cuello, 2026-06-11). Seeding only creates missing rows, so later edits made
on the Templates page survive re-runs.
"""

from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    from referrals.seed_templates import SEED_TEMPLATES

    MessageTemplate = apps.get_model("referrals", "MessageTemplate")
    for key, (subject, body) in SEED_TEMPLATES.items():
        MessageTemplate.objects.get_or_create(
            key=key, defaults={"subject": subject, "body": body},
        )


def unseed(apps, schema_editor):
    from referrals.seed_templates import SEED_TEMPLATES

    MessageTemplate = apps.get_model("referrals", "MessageTemplate")
    MessageTemplate.objects.filter(key__in=SEED_TEMPLATES).delete()


class Migration(migrations.Migration):
    dependencies = [("referrals", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
