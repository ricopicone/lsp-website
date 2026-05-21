"""Smoke tests confirming the project scaffold is sound."""

import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_custom_user_model_persists():
    """The custom user model is wired up and can persist a record."""
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="smoketest",
        email="smoketest@example.com",
        password="not-a-real-password",
    )
    assert user.pk is not None
    assert user_model.objects.count() == 1
