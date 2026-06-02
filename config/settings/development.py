"""Development settings: SQLite, DEBUG enabled, console email."""

from .base import *

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Email is printed to the console during local development (wrapped by the
# persona-safe backend from base — inner backend defaults to console).
