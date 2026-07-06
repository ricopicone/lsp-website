from django.db import migrations


class Migration(migrations.Migration):
    """Remove ``Advancement`` from the ``admissions`` app *state* only.

    The model moved to the ``formation`` app (``formation.0001_initial`` recreates
    it in state on the same ``admissions_advancement`` table). No SQL runs here —
    the table and its data are untouched.
    """

    dependencies = [
        ("admissions", "0002_advancement"),
        ("formation", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="Advancement")],
            database_operations=[],
        ),
    ]
