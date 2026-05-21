from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model for the LSP website.

    Declared from the outset so that AUTH_USER_MODEL is in place before the
    first migration. For now it behaves exactly like Django's default user;
    later Milestone 1 work extends it (email-based login) and adds a related
    Profile carrying the LSP role/status that drives pricing and access.
    """
