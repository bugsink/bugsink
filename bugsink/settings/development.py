from .default import *  # noqa
from .default import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, LOGGING, DATABASES

import os

from debug_toolbar.middleware import show_toolbar

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


SECRET_KEY = 'django-insecure-$@clhhieazwnxnha-_zah&(bieq%yux7#^07&xsvhn58t)8@xw'
DEBUG = True

# > The Debug Toolbar is shown only if your IP address is listed in Django’s INTERNAL_IPS setting. This means that for
# > local development, you must add "127.0.0.1" to INTERNAL_IPS.
INTERNAL_IPS = [
    "127.0.0.1",
]

# TODO monitor https://stackoverflow.com/questions/78476951/why-not-just-set-djangos-allowed-hosts-to
# (also for create_example_conf.py)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
] + MIDDLEWARE


def show_toolbar_for_queryparam(request):
    if "__debug__" not in request.path and not request.GET.get("debug", ""):
        return False
    return show_toolbar(request)


DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": show_toolbar_for_queryparam,
}


# In development, we just keep the databases inside the root directory of the source-code. In production this is "not
# recommended" (very foolish): this path maps to the virualenv's root directory, which is not a good place to store
# databases.
DATABASES["default"]["NAME"] = BASE_DIR / 'db.sqlite3'
DATABASES["default"]["TEST"]["NAME"] = BASE_DIR / 'test.sqlite3'
DATABASES["snappea"]["NAME"] = BASE_DIR / 'snappea.sqlite3'

# {  postponed, for starters we'll do something like SNAPPEA_ALWAYS_EAGER
# DATABASES["snappea"]["TEST"]["NAME"] = BASE_DIR / 'test.snappea.sqlite3'


# {PROTOCOL}://{PUBLIC_KEY}:{DEPRECATED_SECRET_KEY}@{HOST}{PATH}/{PROJECT_ID}
SENTRY_DSN = os.getenv("SENTRY_DSN")


if SENTRY_DSN is not None:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        auto_session_tracking=False,
        traces_sample_rate=0,
        send_default_pii=True,
    )

SNAPPEA = {
    "TASK_ALWAYS_EAGER": False,
    "NUM_WORKERS": 1,
}

POSTMARK_API_KEY = os.getenv('POSTMARK_API_KEY')

EMAIL_HOST = 'smtp.postmarkapp.com'
EMAIL_HOST_USER = POSTMARK_API_KEY
EMAIL_HOST_PASSWORD = POSTMARK_API_KEY
EMAIL_PORT = 587
EMAIL_USE_TLS = True

SERVER_EMAIL = DEFAULT_FROM_EMAIL = 'Klaas van Schelven <klaas@vanschelven.com>'

BUGSINK = {
    "DIGEST_IMMEDIATELY": False,

    # "MAX_EVENT_SIZE": _MEBIBYTE,
    # "MAX_EVENT_COMPRESSED_SIZE": 200 * _KIBIBYTE,
    # "MAX_ENVELOPE_SIZE": 100 * _MEBIBYTE,
    # "MAX_ENVELOPE_COMPRESSED_SIZE": 20 * _MEBIBYTE,

    "BASE_URL": "http://bugsink:9000",  # no trailing slash
    "SITE_TITLE": "Bugsink",  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"
}


# performance development settings: show inline in the console, with a nice little arrow
LOGGING["formatters"]["look_below"] = {
    "format": "    {message} ↴",
    "style": "{",
}

LOGGING["handlers"]["look_below_in_stream"] = {
    "level": "INFO",
    "class": "logging.StreamHandler",
    "formatter": "look_below",
}

LOGGING['loggers']['bugsink.performance']["handlers"] = ["look_below_in_stream"]


# snappea development settings: see all details, and include timestamps (we have no sytemd journal here)
LOGGING["handlers"]["snappea"]["level"] = "DEBUG"
LOGGING["loggers"]["snappea"]["level"] = "DEBUG"
LOGGING["formatters"]["snappea"]["format"] = "{asctime} - {threadName} - {levelname:7} - {message}"
