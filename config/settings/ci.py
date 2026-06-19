from .base import *  # noqa: F403

# Fast in-memory database — no file I/O, discarded after each run
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "ATOMIC_REQUESTS": True,
    }
}

# MD5 is intentionally weak but dramatically speeds up tests that create users
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Capture outgoing emails in memory instead of attempting SMTP
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Console-only logging at ERROR level — no file handlers, no noise
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "ERROR"},
}

CELERY_DEFAULT_QUEUE = "ci"
