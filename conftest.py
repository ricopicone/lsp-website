"""Project-wide pytest fixtures.

The test database must not depend on the clock. Two data migrations
(``payments/0004`` and ``payments/0006``) seed a dues period and a tuition
period named for *today's* academic year — right for a fresh production
database, but in the test database it means the rows that exist change on
September 1, and from that day every test creating "AY 2026–2027" by hand
collided on a unique name or slug (23 tests turned red overnight, nothing in
the code having changed). Strip those seeded rows once, right after the test
database is built, so every test starts from the same empty ledger whatever
the date.
"""

import pytest


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        from payments.models import DuesPeriod, TuitionPeriod

        TuitionPeriod.objects.all().delete()
        DuesPeriod.objects.all().delete()
