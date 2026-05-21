"""Development settings: SQLite, DEBUG enabled, console email."""

from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Email is printed to the console during local development.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
