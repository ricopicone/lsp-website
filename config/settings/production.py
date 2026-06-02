"""Production settings: PostgreSQL, HTTPS hardening, Amazon SES email."""

from .base import *

DEBUG = False

# PostgreSQL connection, read from DATABASE_URL.
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# Whitenoise serves static files directly from the gunicorn process —
# fine for Phase 1 volume; revisit S3 + CloudFront in a later milestone.
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# User uploads: S3 in production when AWS_STORAGE_BUCKET_NAME is set.
# Falls back to local filesystem (FileSystemStorage above) when unset.
# Credentials are picked up from the EC2 instance role via IMDS — no
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in .env.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
if AWS_STORAGE_BUCKET_NAME:
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-west-2")
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "querystring_auth": False,  # public URLs; bucket policy grants read
            "default_acl": None,         # bucket policy handles access
            "file_overwrite": False,     # never silently clobber same-name uploads
        },
    }
    # Public URL hostname for img tags etc.
    MEDIA_URL = (
        f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/"
    )

CSRF_TRUSTED_ORIGINS = env(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["https://app.lacanschool.org"],
)

# --- Channels layer (Parlêtre realtime chat) ----------------------------
# Production runs a single daphne process, so the in-memory channel layer
# from base.py is correct and sufficient (groups are shared within the one
# process — HTTP-fallback broadcasts come from that same process too). We do
# NOT use Redis here: channels-redis against redis-py 8.x raises
# "TimeoutError: Timeout reading from redis" on group ops, which silently
# broke live chat. Re-enable Redis only when scaling to multiple worker
# processes, and only after fixing that combo (e.g. RedisPubSubChannelLayer
# and/or pinning redis-py) — opt in with PARLETRE_USE_REDIS=true.
REDIS_URL = env("REDIS_URL", default="")
if env.bool("PARLETRE_USE_REDIS", default=False) and REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        },
    }

# --- Security (the site is served over HTTPS) ---------------------------

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Email: Amazon SES over SMTP ----------------------------------------
# EMAIL_BACKEND stays the persona-safe wrapper (from base); it delivers through
# this SMTP backend for everyone except persona test accounts.

PERSONA_SAFE_INNER_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("DJANGO_EMAIL_HOST", default="email-smtp.us-west-2.amazonaws.com")
EMAIL_PORT = env.int("DJANGO_EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("DJANGO_EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("DJANGO_EMAIL_HOST_PASSWORD", default="")
