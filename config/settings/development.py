"""Development settings: SQLite, DEBUG enabled, console email."""

from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Parlêtre's school-wide social + private chats are hidden in production (task
# #360, base defaults off), but developers and the test suite exercise the full
# board, so they default ON here. The disable is verified explicitly in
# parletre/test_social_disable.py via override_settings.
PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED = True
PARLETRE_PRIVATE_CHATS_ENABLED = True

# Email is printed to the console during local development (wrapped by the
# persona-safe backend from base — inner backend defaults to console).
