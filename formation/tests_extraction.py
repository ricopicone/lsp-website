import pytest
from django.apps import apps


@pytest.mark.django_db
def test_advancement_lives_in_formation_on_the_same_table():
    Advancement = apps.get_model("formation", "Advancement")
    assert Advancement._meta.db_table == "admissions_advancement"


@pytest.mark.django_db
def test_migrations_have_no_pending_changes():
    # Fails if state and models drift (the SeparateDatabaseAndState split is wrong).
    from django.core.management import call_command
    call_command("makemigrations", "--check", "--dry-run", "formation", "admissions")
