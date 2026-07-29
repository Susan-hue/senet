import os
import ssl
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import Csv, config
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config("DEBUG", default=True, cast=bool)
SECRET_KEY = config("SECRET_KEY", default="")

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = get_random_secret_key()
    else:
        raise ValueError("SECRET_KEY must be set when DEBUG is False")

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "tenancy",
    "accounts",
    "results",
    "assessments",
    "grading",
    "auditor",
    "cbt",
    "notifications",
]

MIDDLEWARE = [
    "config.health.HealthCheckMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "tenancy.middleware.CurrentInstitutionMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# A test run must never touch the production database. Detect both runners:
# `manage.py test` puts "test" in argv, while pytest sets PYTEST_VERSION in the
# environment (and is imported into sys.modules) before settings are read.
TESTING = (
    "test" in sys.argv
    or "PYTEST_VERSION" in os.environ
    or "pytest" in sys.modules
    or os.path.basename(sys.argv[0]) in ("pytest", "py.test")
)

_SQLITE_DEFAULT = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
}

DATABASE_URL = config("DATABASE_URL", default="")
DATABASE_URL_TEST = config("DATABASE_URL_TEST", default="")

if TESTING:
    # Defense in depth: refuse to run the suite against the production DB even
    # if someone points DATABASE_URL_TEST at it. Without an explicit test URL we
    # fall back to a throwaway SQLite file, never the production DATABASE_URL.
    if DATABASE_URL and DATABASE_URL_TEST == DATABASE_URL:
        raise ValueError("DATABASE_URL_TEST must not equal the production DATABASE_URL")
    if DATABASE_URL_TEST:
        DATABASES = {"default": dj_database_url.parse(DATABASE_URL_TEST, conn_max_age=0)}
    else:
        DATABASES = {"default": _SQLITE_DEFAULT}
elif DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
elif DEBUG:
    DATABASES = {"default": _SQLITE_DEFAULT}
else:
    raise ValueError("DATABASE_URL must be set when DEBUG is False")

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "EXCEPTION_HANDLER": "accounts.responses.envelope_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (),
    "DEFAULT_THROTTLE_RATES": {
        # Registering a phone for the SMS result check sends a real OTP text.
        "result_check_otp": config("RESULT_CHECK_OTP_RATE", default="5/hour"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

AUTH_REFRESH_COOKIE_NAME = "refresh_token"
AUTH_REFRESH_COOKIE_PATH = "/api/v1/auth/"
AUTH_REFRESH_COOKIE_SAMESITE = config("AUTH_REFRESH_COOKIE_SAMESITE", default="None")
AUTH_REFRESH_COOKIE_SECURE = config("AUTH_REFRESH_COOKIE_SECURE", default=True, cast=bool)

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="no-reply@senet.local")
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173")

if EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend":
    EMAIL_HOST = config("EMAIL_HOST")
    EMAIL_HOST_USER = config("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = config("RESEND_API_KEY")
    EMAIL_PORT = config("EMAIL_PORT", cast=int)
    EMAIL_USE_TLS = config("EMAIL_USE_TLS", cast=bool)

EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24
PASSWORD_RESET_MAX_AGE = 60 * 60

IMPORT_MAX_FILE_BYTES = config("IMPORT_MAX_FILE_BYTES", default=5 * 1024 * 1024, cast=int)
IMPORT_SYNC_MAX_ROWS = config("IMPORT_SYNC_MAX_ROWS", default=500, cast=int)

# Classes larger than this have their exports (broadsheet / OGR) generated on the
# Celery worker rather than inline in the request.
EXPORT_ASYNC_THRESHOLD = config("EXPORT_ASYNC_THRESHOLD", default=200, cast=int)

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")

CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=DEBUG, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

_CELERY_SSL_CERT_REQS = {
    "required": ssl.CERT_REQUIRED,
    "optional": ssl.CERT_OPTIONAL,
    "none": ssl.CERT_NONE,
}[config("CELERY_SSL_CERT_REQS", default="required").lower()]

if CELERY_BROKER_URL.startswith("rediss://"):
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": _CELERY_SSL_CERT_REQS}
if CELERY_RESULT_BACKEND.startswith("rediss://"):
    CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": _CELERY_SSL_CERT_REQS}

# How often Celery beat sweeps for exam attempts past their deadline and
# auto-submits them. Short by design — the finalizer is idempotent and row-locked,
# so frequent, overlapping runs are safe.
CBT_FINALIZE_INTERVAL_SECONDS = config("CBT_FINALIZE_INTERVAL_SECONDS", default=60, cast=int)

# Proctoring webcam media limits. Snapshots are small images; short clips a few MB.
CBT_WEBCAM_MAX_FILE_BYTES = config("CBT_WEBCAM_MAX_FILE_BYTES", default=8 * 1024 * 1024, cast=int)
CBT_WEBCAM_ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".webm", ".mp4")

# AI question generation (Grok / xAI). Key comes from the environment, never code.
GROK_API_KEY = config("GROK_API_KEY", default="")
GROK_API_URL = config("GROK_API_URL", default="https://api.x.ai/v1/chat/completions")
GROK_MODEL = config("GROK_MODEL", default="grok-4")
GROK_TIMEOUT_SECONDS = config("GROK_TIMEOUT_SECONDS", default=30, cast=int)
CBT_AI_MAX_QUESTIONS = config("CBT_AI_MAX_QUESTIONS", default=20, cast=int)
# --------------------------------------------------------------------------- #
# Notifications (email / SMS / WhatsApp) + SMS-USSD result check               #
# --------------------------------------------------------------------------- #

# Termii is the Nigeria-native SMS/WhatsApp provider. Every credential is read
# from the environment; nothing here is ever a literal.
TERMII_API_KEY = config("TERMII_API_KEY", default="")
TERMII_BASE_URL = config("TERMII_BASE_URL", default="https://api.ng.termii.com")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="Senet")
TERMII_WHATSAPP_SENDER_ID = config("TERMII_WHATSAPP_SENDER_ID", default=TERMII_SENDER_ID)
TERMII_TIMEOUT_SECONDS = config("TERMII_TIMEOUT_SECONDS", default=15, cast=int)

# Shared secret Termii signs inbound SMS/USSD webhooks with. Deliberately has no
# default: with no secret configured the inbound endpoints reject everything
# rather than trusting an unauthenticated caller.
TERMII_INBOUND_SECRET = config("TERMII_INBOUND_SECRET", default="")

# Without a Termii key (local dev, CI) sending falls back to the console provider
# so nothing silently tries to reach the real network.
_DEFAULT_TEXT_PROVIDER = (
    "notifications.providers.TermiiProvider"
    if TERMII_API_KEY
    else "notifications.providers.ConsoleProvider"
)
NOTIFICATION_PROVIDERS = {
    "email": config(
        "NOTIFICATIONS_EMAIL_PROVIDER", default="notifications.providers.DjangoEmailProvider"
    ),
    "sms": config("NOTIFICATIONS_SMS_PROVIDER", default=_DEFAULT_TEXT_PROVIDER),
    "whatsapp": config("NOTIFICATIONS_WHATSAPP_PROVIDER", default=_DEFAULT_TEXT_PROVIDER),
}
NOTIFICATIONS_WHATSAPP_ENABLED = config("NOTIFICATIONS_WHATSAPP_ENABLED", default=False, cast=bool)
NOTIFICATION_MAX_RETRIES = config("NOTIFICATION_MAX_RETRIES", default=3, cast=int)
NOTIFICATION_RETRY_BACKOFF_SECONDS = config(
    "NOTIFICATION_RETRY_BACKOFF_SECONDS", default=30, cast=int
)

# Default country for normalising locally-dialled Nigerian numbers to E.164.
SMS_DEFAULT_COUNTRY_CODE = config("SMS_DEFAULT_COUNTRY_CODE", default="234")

# SMS/USSD result check. Results day is a whole campus checking at once, so the
# lookup is cached and rate-limited per phone number rather than per source IP
# (every request arrives from the provider's gateway).
RESULT_CHECK_CACHE_SECONDS = config("RESULT_CHECK_CACHE_SECONDS", default=300, cast=int)
RESULT_CHECK_RATE_LIMIT = config("RESULT_CHECK_RATE_LIMIT", default=5, cast=int)
RESULT_CHECK_RATE_WINDOW_SECONDS = config("RESULT_CHECK_RATE_WINDOW_SECONDS", default=60, cast=int)
RESULT_CHECK_MAX_FAILURES = config("RESULT_CHECK_MAX_FAILURES", default=5, cast=int)
RESULT_CHECK_LOCKOUT_SECONDS = config("RESULT_CHECK_LOCKOUT_SECONDS", default=900, cast=int)
RESULT_CHECK_PIN_MIN_LENGTH = config("RESULT_CHECK_PIN_MIN_LENGTH", default=4, cast=int)
RESULT_CHECK_PIN_MAX_LENGTH = config("RESULT_CHECK_PIN_MAX_LENGTH", default=6, cast=int)
RESULT_CHECK_OTP_TTL_SECONDS = config("RESULT_CHECK_OTP_TTL_SECONDS", default=600, cast=int)
USSD_SESSION_TTL_SECONDS = config("USSD_SESSION_TTL_SECONDS", default=180, cast=int)

# How often beat looks for exams that have just opened so their students are
# notified once. Dedupe is by notification key, so overlapping runs are safe.
EXAM_OPEN_SWEEP_INTERVAL_SECONDS = config("EXAM_OPEN_SWEEP_INTERVAL_SECONDS", default=300, cast=int)

CACHE_URL = config("CACHE_URL", default="")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "senet-default",
        }
    }

CELERY_BEAT_SCHEDULE = {
    "cbt-finalize-expired-attempts": {
        "task": "cbt.tasks.finalize_expired_attempts_task",
        "schedule": float(CBT_FINALIZE_INTERVAL_SECONDS),
    },
    "notifications-sweep-opened-exams": {
        "task": "notifications.tasks.notify_opened_exams",
        "schedule": float(EXAM_OPEN_SWEEP_INTERVAL_SECONDS),
    },
}

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = (
    config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv()) or CORS_ALLOWED_ORIGINS
)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Supabase Storage exposes an S3-compatible endpoint; when configured, student
# uploads are stored there instead of on the app server's disk.
SUPABASE_S3_BUCKET = config("SUPABASE_S3_BUCKET", default="")
if SUPABASE_S3_BUCKET:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": SUPABASE_S3_BUCKET,
            "endpoint_url": config("SUPABASE_S3_ENDPOINT_URL"),
            "access_key": config("SUPABASE_S3_ACCESS_KEY_ID"),
            "secret_key": config("SUPABASE_S3_SECRET_ACCESS_KEY"),
            "region_name": config("SUPABASE_S3_REGION", default="eu-central-1"),
            "default_acl": "private",
            "file_overwrite": False,
            "signature_version": "s3v4",
        },
    }

ASSESSMENT_MAX_FILE_BYTES = config("ASSESSMENT_MAX_FILE_BYTES", default=10 * 1024 * 1024, cast=int)
ASSESSMENT_ALLOWED_EXTENSIONS = (".pdf", ".doc", ".docx")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)

    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
