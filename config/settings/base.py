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
    "admissions",
    "committees",
    "content",
    "documents",
    "events",
    "registrations",
    "payments",
    "works",
    "parletre",
    "notifications",
    "workgroups",
    "cartels",
    "workinggroups",
    "video",
    "suggestions",
    "referrals",
    "availability",
    "devapi",
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
    "accounts.middleware.TwoFactorEnforcementMiddleware",
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
                "core.context_processors.survey_nudge",
                "core.context_processors.preview_tour",
                "core.context_processors.site_theme",
                "core.context_processors.page_artwork",
                "notifications.context_processors.bell",
                "suggestions.context_processors.widget",
                "admissions.context_processors.my_lsp_tabs",
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

# Leading slash so headshot.url is a root-absolute path ("/media/…") rather
# than one relative to the current page — otherwise an <img> on /accounts/profile/
# resolves it to /accounts/media/… and 404s. Production overrides this with the
# absolute S3 URL, so this only governs local-disk dev.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Access-controlled uploads (gated Work/Document PDFs, workgroup working-doc
# files, Parlêtre attachments) live OUTSIDE the public media root — a private
# S3 bucket in production, or this local dir in dev. Served only through the
# access-checked download views; never a bare public URL. See core.storage.
PRIVATE_MEDIA_ROOT = env(
    "PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private-media")
)
# Back-compat alias (Parlêtre attachments shared this root).
PARLETRE_ATTACHMENTS_ROOT = env(
    "PARLETRE_ATTACHMENTS_ROOT", default=PRIVATE_MEDIA_ROOT
)
# Applicant CVs are personal — kept off the public bucket, served only via the
# access-checked download view (admissions.views.cv_download).
ADMISSIONS_UPLOADS_ROOT = env(
    "ADMISSIONS_UPLOADS_ROOT", default=str(BASE_DIR / "private-media" / "admissions")
)

# Private S3 bucket for the above (unset → local filesystem fallback). The
# public default-storage bucket is configured separately in production.py.
AWS_PRIVATE_STORAGE_BUCKET_NAME = env("AWS_PRIVATE_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-west-2")

# --- Email --------------------------------------------------------------

# The bare sending address (e.g. no-reply@lacanschool.org). Inboxes show the
# local part ("no-reply") as the sender name unless a display name is attached,
# so we wrap it with EMAIL_FROM_NAME below — every email then shows a friendly
# "From" (e.g. "Lacanian School of Psychoanalysis <no-reply@lacanschool.org>").
# Per-type senders can substitute their own name via core.email.school_from().
DEFAULT_FROM_ADDRESS = env("DJANGO_DEFAULT_FROM_EMAIL", default="webmaster@localhost")
EMAIL_FROM_NAME = env("DJANGO_EMAIL_FROM_NAME", default="Lacanian School of Psychoanalysis")
if "@" in DEFAULT_FROM_ADDRESS and "<" not in DEFAULT_FROM_ADDRESS:
    from email.utils import formataddr as _formataddr

    DEFAULT_FROM_EMAIL = _formataddr((EMAIL_FROM_NAME, DEFAULT_FROM_ADDRESS))
else:
    DEFAULT_FROM_EMAIL = DEFAULT_FROM_ADDRESS
SUPPORT_EMAIL = env("DJANGO_SUPPORT_EMAIL", default="website@lacanschool.org")
# The Referral Coordinator's mailbox: Find-an-Analyst inquiries land here, and
# referral-flow mail (acknowledgments, distributions, follow-ups) carries it
# as Reply-To so any reply reaches the coordinator.
REFERRALS_EMAIL = env("DJANGO_REFERRALS_EMAIL", default="referrals@lacanschool.org")

# All mail flows through a persona-safe wrapper that never delivers to persona
# test accounts (their addresses aren't real mailboxes). Each environment sets
# the *inner* backend it wraps.
EMAIL_BACKEND = "core.email.PersonaSafeEmailBackend"
PERSONA_SAFE_INNER_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Self-service login-email change (accounts.views.email_change). Gated until
# launch: until EMAIL_CHANGE_PUBLIC is True, only addresses in
# EMAIL_CHANGE_ALLOWLIST see the option and may initiate a change. Default
# allowlist is the project owner's address for testing while SES is still in
# sandbox (it only delivers to verified identities anyway).
EMAIL_CHANGE_PUBLIC = env.bool("DJANGO_EMAIL_CHANGE_PUBLIC", default=False)
EMAIL_CHANGE_ALLOWLIST = env.list(
    "DJANGO_EMAIL_CHANGE_ALLOWLIST", default=["dr@ricopic.one"]
)

# --- Two-factor auth (TOTP) ---------------------------------------------
# 2FA *enrollment* (authenticator setup at /accounts/2fa/setup/) is always
# available. The *requirement* — forcing enrollment + a per-session challenge
# for anyone with an admin role (accounts.twofactor.requires_2fa) — is gated
# here and ships OFF so current testers aren't blocked. Flip
# DJANGO_TWO_FACTOR_ENFORCED=true at launch to switch enforcement on.
TWO_FACTOR_ENFORCED = env.bool("DJANGO_TWO_FACTOR_ENFORCED", default=False)

# Max sustained send rate (messages/second) for the batch reminder jobs
# (payments.sending.ThrottledSender). SES caps sends — 1/s in the sandbox,
# higher once production access is granted — and returns a transient 454
# "Throttling failure" when exceeded. Keep this at or below the SES
# MaxSendRate (`aws sesv2 get-account`); the default is sandbox-safe. Raise
# via DJANGO_EMAIL_MAX_SEND_RATE once out of the sandbox.
EMAIL_MAX_SEND_RATE = env.float("DJANGO_EMAIL_MAX_SEND_RATE", default=1.0)

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

# When True, the webhook ignores Stripe *test*-mode events (livemode=false) so
# test data can never enter real accounting. Off in development (so the flow
# can be exercised with test keys); ON in production — see production.py.
STRIPE_LIVE_ONLY = env.bool("STRIPE_LIVE_ONLY", default=False)

# --- Daily.co video rooms -----------------------------------------------
# In-site, browser-based meeting rooms (one persistent room per Workgroup,
# provisioned lazily on first join). Off by default until the school's Daily
# key is on the host; mirrors the SURVEY_ENABLED / STRIPE_LIVE_ONLY pattern.
# Recording is never enabled (case-history privacy). See the video app.
DAILY_ENABLED = env.bool("DJANGO_DAILY_ENABLED", default=False)
DAILY_API_KEY = env("DAILY_API_KEY", default="")
DAILY_DOMAIN = env("DAILY_DOMAIN", default="")            # e.g. lsp.daily.co
DAILY_API_URL = env("DAILY_API_URL", default="https://api.daily.co/v1")
DAILY_TOKEN_TTL_MINUTES = env.int("DJANGO_DAILY_TOKEN_TTL_MINUTES", default=180)
DAILY_MAX_PARTICIPANTS = env.int("DJANGO_DAILY_MAX_PARTICIPANTS", default=0)  # 0 = unset

# Recording (opt-in; hosts start it, special events auto-start). Recordings are
# stored on Daily by default; set RECORDING_OWN_S3=true + AWS_RECORDINGS_BUCKET_NAME
# (and Daily's domain recordings_bucket) to own them in our S3. The webhook secret
# is the base64 HMAC secret configured on the Daily webhook.
DAILY_WEBHOOK_SECRET = env("DAILY_WEBHOOK_SECRET", default="")
RECORDING_OWN_S3 = env.bool("DJANGO_RECORDING_OWN_S3", default=False)
AWS_RECORDINGS_BUCKET_NAME = env("AWS_RECORDINGS_BUCKET_NAME", default="")
RECORDING_RETENTION_DAYS = env.int("DJANGO_RECORDING_RETENTION_DAYS", default=365)

# Launch intake survey: when True, members are nudged (banner + dropdown link)
# to complete the onboarding survey. Off until launch; the page itself stays
# reachable at /accounts/survey/ for testing. Flip via DJANGO_SURVEY_ENABLED.
SURVEY_ENABLED = env.bool("SURVEY_ENABLED", default=False)

# Limited-preview onboarding tour: a dismissible task checklist (every page) plus
# contextual hints (e.g. on the profile photo chooser) that guide a small
# preview cohort through their first tasks. Off by default; flip
# DJANGO_PREVIEW_TOUR_ENABLED=true to switch it on. PREVIEW_TOUR_ALLOWLIST
# restricts it to specific addresses while enabled — an empty list means every
# authenticated user sees it. Mirrors the EMAIL_CHANGE_* gating.
PREVIEW_TOUR_ENABLED = env.bool("DJANGO_PREVIEW_TOUR_ENABLED", default=False)
# When True, the tour shows for every authenticated user, ignoring the
# allowlist (mirrors EMAIL_CHANGE_PUBLIC). Flip on to broaden the preview
# beyond the named cohort.
PREVIEW_TOUR_PUBLIC = env.bool("DJANGO_PREVIEW_TOUR_PUBLIC", default=False)

# Member suggestion box: when True, members see the floating "Suggest a change"
# widget and the /suggestions/ form, and may file suggestions; staff triage them
# at /admin-tools/suggestions/. Off until launch (like SURVEY_ENABLED). Flip via
# DJANGO_SUGGESTIONS_ENABLED.
SUGGESTIONS_ENABLED = env.bool("DJANGO_SUGGESTIONS_ENABLED", default=False)

# Web-developer API (/devapi/): token-authenticated JSON surface a Claude Code
# session uses to read + triage the work the site produces (member suggestions
# today). Independent of SUGGESTIONS_ENABLED — the dev needs API access before
# the box opens to members. On by default; every request still needs a valid
# bearer token. Set DJANGO_DEVAPI_ENABLED=false to kill the surface entirely.
DEVAPI_ENABLED = env.bool("DJANGO_DEVAPI_ENABLED", default=True)
PREVIEW_TOUR_ALLOWLIST = env.list(
    "DJANGO_PREVIEW_TOUR_ALLOWLIST", default=["dr@ricopic.one"]
)
# Slug of the sandbox seminar the tour's "Register" task points at. Created by
# `manage.py seed_preview_seminar` ($0 tier → registration skips Stripe). The
# checklist links here and auto-ticks once the member has an active
# registration for it.
PREVIEW_TOUR_SEMINAR_SLUG = env("DJANGO_PREVIEW_TOUR_SEMINAR_SLUG", default="preview-seminar")
# Slug of the open Parlêtre chat channel the tour's "Say hello" task points at.
# Created by `manage.py seed_preview`. The checklist auto-ticks once the member
# has posted there.
PREVIEW_TOUR_CHANNEL_SLUG = env("DJANGO_PREVIEW_TOUR_CHANNEL_SLUG", default="welcome")

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
