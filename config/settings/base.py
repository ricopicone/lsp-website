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
    # daphne must precede staticfiles so it can provide the ASGI runserver.
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "phonenumber_field",
]

LOCAL_APPS = [
    "accounts",
    "committees",
    "content",
    "documents",
    "events",
    "registrations",
    "payments",
    "works",
    "parletre",
    "workgroups",
    "cartels",
    "workinggroups",
    "core",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Parse phone numbers without a country code as US numbers.
PHONENUMBER_DEFAULT_REGION = "US"
PHONENUMBER_DEFAULT_FORMAT = "E164"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.TimezoneMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.ImpersonationMiddleware",
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
                "core.context_processors.aphorism",
                "parletre.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Channels layer for Parlêtre realtime chat (M13.5b). In-memory is fine for a
# single process (dev, tests, and a single-worker prod box); production sets
# REDIS_URL to share the layer across workers (see production.py).
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

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
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

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
STATICFILES_DIRS = [BASE_DIR / "static"]  # Tailwind build output, future shared assets

# --- Media files (user uploads — e.g. faculty headshots) ---------------
# Local-disk storage for Phase 1. Move to S3 + django-storages in a later
# milestone, once a faculty-facing upload UI exists and we need durability
# across container restarts.

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Parlêtre attachments live OUTSIDE the public media root (and outside the
# public S3 bucket) and are served only through the access-checked download
# view, so files in a private channel stay private. Persist this directory in
# production the same way media is persisted (a bind-mount), so attachments
# survive container restarts.
PARLETRE_ATTACHMENTS_ROOT = env(
    "PARLETRE_ATTACHMENTS_ROOT", default=str(BASE_DIR / "private-media")
)

# --- Email --------------------------------------------------------------

DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="webmaster@localhost")
SUPPORT_EMAIL = env("DJANGO_SUPPORT_EMAIL", default="website@lacanschool.org")

# Self-service login-email change (accounts.views.email_change). Gated until
# launch: until EMAIL_CHANGE_PUBLIC is True, only addresses in
# EMAIL_CHANGE_ALLOWLIST see the option and may initiate a change. Default
# allowlist is the project owner's address for testing while SES is still in
# sandbox (it only delivers to verified identities anyway).
EMAIL_CHANGE_PUBLIC = env.bool("DJANGO_EMAIL_CHANGE_PUBLIC", default=False)
EMAIL_CHANGE_ALLOWLIST = env.list(
    "DJANGO_EMAIL_CHANGE_ALLOWLIST", default=["dr@ricopic.one"]
)

# --- Parlêtre (discussion board) email -----------------------------------
# Reply-by-email: when enabled, notification emails carry a signed Reply-To
# at PARLETRE_REPLY_DOMAIN so a member's reply posts back to the thread.
# Disabled by default until SES inbound is provisioned for that subdomain
# (see the Phase 2 plan's parallel-prep tasks); until then notification
# emails just use SUPPORT_EMAIL as Reply-To.
PARLETRE_REPLY_ENABLED = env.bool("PARLETRE_REPLY_ENABLED", default=False)
PARLETRE_REPLY_DOMAIN = env("PARLETRE_REPLY_DOMAIN", default="parletre.lacanschool.org")
# Secret for signing reply tokens (HMAC). Falls back to SECRET_KEY.
PARLETRE_REPLY_SECRET = env("PARLETRE_REPLY_SECRET", default=SECRET_KEY)
# Inbound webhook (SES → SNS → /parletre/inbound/). The security boundary is
# the HMAC reply token + sender match; this optional SNS topic-ARN allowlist
# is cheap defence-in-depth. Full SNS signature verification is a hardening
# follow-up. Set to the receiving topic's ARN to reject other senders.
PARLETRE_SNS_TOPIC_ARN = env("PARLETRE_SNS_TOPIC_ARN", default="")

# --- Stripe -------------------------------------------------------------
# Test-mode keys for development; production keys swapped via env in
# production.py. STRIPE_WEBHOOK_SECRET is the signing secret for the
# Stripe webhook endpoint (whsec_...).

STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

# Public base URL used to build Stripe Checkout success/cancel return URLs.
SITE_BASE_URL = env("SITE_BASE_URL", default="http://localhost:8000")

# Annual LSP membership dues (REG-12) — tiered by role. Used as seed
# amounts for a brand-new DuesPeriod; once a DuesPeriod row exists for
# the current AY, its tier fields are authoritative.
DUES_PRE_CANDIDATE_AMOUNT = env("DUES_PRE_CANDIDATE_AMOUNT", default="50.00")
DUES_CANDIDATE_AMOUNT     = env("DUES_CANDIDATE_AMOUNT",     default="100.00")
DUES_ANALYST_AMOUNT       = env("DUES_ANALYST_AMOUNT",       default="150.00")

# Profile.role values that owe annual dues. The default matches the three
# tiers above — pre-candidates (analyst + scholar track), candidates (both
# tracks), and analysts/scholars. MEMBER and STUDENT are not billed
# separately (Members are already captured by the in-training + analyst /
# scholar roles in practice).
DUES_OBLIGATED_ROLES = env.list(
    "DUES_OBLIGATED_ROLES",
    default=[
        "pre_candidate", "pre_candidate_scholar",
        "candidate", "candidate_scholar",
        "analyst", "scholar",
    ],
)

# Annual student tuition (M7.5). Mirrors DUES_ANNUAL_AMOUNT — the value
# is the seed for a new TuitionPeriod; once a period exists, its
# ``tuition_amount`` is authoritative.
TUITION_ANNUAL_AMOUNT = env("TUITION_ANNUAL_AMOUNT", default="800.00")

# --- Logging ------------------------------------------------------------
# Django's default LOGGING only sends to the console when DEBUG=True, so
# production 5xx tracebacks vanish. Send them to stderr (which Docker
# captures) unconditionally.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "payments": {"handlers": ["console"], "level": "INFO"},
        "events": {"handlers": ["console"], "level": "INFO"},
        "registrations": {"handlers": ["console"], "level": "INFO"},
    },
}

# --- Defaults -----------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
