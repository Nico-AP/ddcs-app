from pathlib import Path

import ddm.core

from .base import *  # noqa: F403
from .base import DEBUG, INSTALLED_APPS, LOGGING, MIDDLEWARE, env

# Cache
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}


# Email
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend

EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)


# Logging
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging

LOGGING["loggers"]["django"]["handlers"].append("console")
LOGGING["loggers"]["django.request"]["handlers"].append("console")
LOGGING["loggers"]["django.security"]["handlers"].append("console")


# django-debug-toolbar - https://github.com/django-commons/django-debug-toolbar
# ------------------------------------------------------------------------------
if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
    DEBUG_TOOLBAR_CONFIG = {
        "DISABLE_PANELS": [
            "debug_toolbar.panels.redirects.RedirectsPanel",
            # Disable profiling panel due to an issue with Python 3.12:
            # https://github.com/jazzband/django-debug-toolbar/issues/1875
            "debug_toolbar.panels.profiling.ProfilingPanel",
        ],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
    INTERNAL_IPS = ["127.0.0.1"]


# DDM
# ------------------------------------------------------------------------------
WEBPACK_LOADER = {
    "DDM_UPLOADER": {
        "CACHE": False,
        "BUNDLE_DIR_NAME": "core/frontend/uploader/",
        "STATS_FILE": Path(ddm.core.__file__).parent
        / "static/ddm_core/frontend/uploader/webpack-stats.json",
        "POLL_INTERVAL": 0.1,  # Adjust as needed
        "IGNORE": [r".+\.hot-update.js", r".+\.map"],
    },
    "DDM_QUESTIONNAIRE": {
        "CACHE": False,
        "BUNDLE_DIR_NAME": "core/frontend/questionnaire/",
        "STATS_FILE": Path(ddm.core.__file__).parent
        / "static/ddm_core/frontend/questionnaire/webpack-stats.json",
        "POLL_INTERVAL": 0.1,  # Adjust as needed
        "IGNORE": [r".+\.hot-update.js", r".+\.map"],
    },
}
