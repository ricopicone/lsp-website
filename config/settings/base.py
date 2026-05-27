"""
Base settings shared by every environment.

Environment-specific overrides live in development.py and production.py.
Choose an environment with the DJANGO_SETTINGS_MODULE variable; it defaults
to config.settings.development (set in manage.py, wsgi.py and asgi.py).
"""

from pathlib import Path

import environ

# Repository root. This file is config/settings/base.py, so the root is
# three directories up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
)

# Load a .env file when present — a convenience for local development.
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(env_file)

# --- Core ---------------------------------------------------------------

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="insecure-development-key-override-in-production",
)

DEBUG = env("DJANGO_DEBUG")

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# --- Applications -------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "accounts",
    "events",
    "registrations",
    "payments",
    "core",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -----------------------------------------------------------
# Development uses this SQLite database. Production overrides DATABASES
# with a PostgreSQL connection read from DATABASE_URL.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
}

# --- Authentication -----------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ----------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="America/Los_Angeles")
USE_I18N = True
USE_TZ = True

# --- Static files -------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Media files (user uploads — e.g. faculty headshots) ---------------
# Local-disk storage for Phase 1. Move to S3 + django-storages in a later
# milestone, once a faculty-facing upload UI exists and we need durability
# across container restarts.

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Email --------------------------------------------------------------

DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="webmaster@localhost")

# --- Defaults -----------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
