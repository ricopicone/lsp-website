"""Point the FormationSettings formation-doc links at the seeded guideline
Documents when they exist, so the Formation-tab link works on deploy without a
manual admin step. Repointable in admin afterward; a no-op if the docs or the
singleton are absent, and it never overwrites a link already set."""

from django.db import migrations

_DEFAULTS = {
    "analyst_formation_doc": "analyst-formation-guidelines",
    "scholar_formation_doc": "scholar-formation-guidelines",
}


def seed_links(apps, schema_editor):
    FormationSettings = apps.get_model("formation", "FormationSettings")
    Document = apps.get_model("documents", "Document")

    settings_obj = FormationSettings.objects.filter(pk=1).first()
    if settings_obj is None:
        return

    changed = False
    for field, slug in _DEFAULTS.items():
        if getattr(settings_obj, f"{field}_id") is not None:
            continue
        doc = Document.objects.filter(slug=slug).first()
        if doc is not None:
            setattr(settings_obj, field, doc)
            changed = True
    if changed:
        settings_obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ("formation", "0005_formationsettings_analyst_formation_doc_and_more"),
        ("documents", "0006_alter_document_file"),
    ]

    operations = [
        migrations.RunPython(seed_links, migrations.RunPython.noop),
    ]
