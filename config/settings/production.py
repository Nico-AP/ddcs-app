from pathlib import Path

from csp.constants import NONE, SELF, UNSAFE_INLINE

from .base import *  # noqa: F403
from .base import REDIS_URL, STATIC_ROOT, env

# Database
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": env.str("DJANGO_DB_ENGINE"),
        "HOST": env.str("DJANGO_DB_HOST"),
        "NAME": env.str("DJANGO_DB_NAME"),
        "USER": env.str("DJANGO_DB_USER"),
        "PASSWORD": env.str("DJANGO_DB_PW"),
        "OPTIONS": {"sslmode": "require"},
        "ATOMIC_REQUESTS": True,
    }
}


# Security
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/5.2/topics/security/
# https://owasp.org/Top10/2025/

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_AGE = 86400  # 1 day
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 31536000  # = 1 year
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "SAMEORIGIN"

# django-csp - https://django-csp.readthedocs.io/en/latest/configuration.html

CONTENT_SECURITY_POLICY = {
    "INCLUDE_NONCE_IN": ["script-src"],
    "DIRECTIVES": {
        "default-src": [NONE],
        "script-src": [
            SELF,
            "https://analytics.dein-feed-deine-wahl.de",
            "https://www.tiktok.com",
            UNSAFE_INLINE,  # TODO: Remove again when htmx issue is figured out
        ],
        "style-src": [
            SELF,
            UNSAFE_INLINE,  # required for Plotly dynamic styles + htmx styles
        ],
        "img-src": [
            SELF,
            "data:",
            "blob:",  # Plotly.toImage rasterises the chart via a blob: URL
            "*.stuttgarter-zeitung.de",
            "*.br.de",
            "*.fu-berlin.de",
            "*.tagesspiegel.de",
            "*.tiktokcdn.com",
            "*.tiktokcdn-eu.com",
            "*.muscdn.com",
        ],
        "media-src": [SELF, "https://www.tiktok.com"],
        "font-src": [SELF],
        "frame-src": ["https://www.tiktok.com"],
        "connect-src": [
            SELF,
            "https://analytics.dein-feed-deine-wahl.de",
            "https://www.tiktok.com",
        ],
        "frame-ancestors": [NONE],
        "base-uri": [NONE],
        "form-action": [SELF],
    },
}


# Email
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#default-from-email
DEFAULT_FROM_EMAIL = env.str(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default="contact <noreply@example.com>",
)
EMAIL_HOST = env.str("EMAIL_HOST")
EMAIL_PORT = env.int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env.str("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD")

# https://docs.djangoproject.com/en/dev/ref/settings/#server-email
SERVER_EMAIL = env.str("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env.str(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="",
)


# Cache
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# DDM
# ------------------------------------------------------------------------------
WEBPACK_LOADER = {
    "DDM_UPLOADER": {
        "CACHE": True,
        "BUNDLE_DIR_NAME": "ddm_core/frontent/uploader/",
        "STATS_FILE": Path(STATIC_ROOT)
        / "ddm_core/frontend/uploader/webpack-stats.json",
        "POLL_INTERVAL": 0.1,
        "IGNORE": [r".+\.hot-update.js", r".+\.map"],
    },
    "DDM_QUESTIONNAIRE": {
        "CACHE": True,
        "BUNDLE_DIR_NAME": "ddm_core/frontend/questionnaire/",
        "STATS_FILE": Path(STATIC_ROOT)
        / "ddm_core/frontend/questionnaire/webpack-stats.json",
        "POLL_INTERVAL": 0.1,
        "TIMEOUT": None,
        "IGNORE": [r".+\.hot-update.js", r".+\.map"],
    },
}
