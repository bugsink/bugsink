from .default import *  # noqa
from .default import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, LOGGING, DATABASES, I_AM_RUNNING

import os

from sentry_sdk_extensions.transport import MoreLoudlyFailingTransport
from debug_toolbar.middleware import show_toolbar

from bugsink.utils import deduce_allowed_hosts, eat_your_own_dogfood


SECRET_KEY = 'django-insecure-$@clhhieazwnxnha-_zah&(bieq%yux7#^07&xsvhn58t)8@xw'
DEBUG = True


# > The Debug Toolbar is shown only if your IP address is listed in Django’s INTERNAL_IPS setting. This means that for
# > local development, you must add "127.0.0.1" to INTERNAL_IPS.
INTERNAL_IPS = [
    "127.0.0.1",
]

if not I_AM_RUNNING == "TEST":
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


# this way of configuring (DB, DB_USER, DB_PASSWORD) is specific to the development environment
if os.getenv("DB", "sqlite") == "mysql":
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'bugsink',
        'USER': os.environ["DB_USER"],
        'PASSWORD': os.environ["DB_PASSWORD"],
    }

elif os.getenv("DB", "sqlite") == "postgres":
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'bugsink',
        'USER': os.environ["DB_USER"],
        'PASSWORD': os.environ["DB_PASSWORD"],
        'HOST': 'localhost',
    }

elif os.getenv("DB", "sqlite") == "sqlite":
    # In development, we just keep the databases inside the root directory of the source-code. In production this is
    # "not recommended" (very foolish): this path maps to the virualenv's root directory, which is not a good place to
    # store databases.
    DATABASES["default"]["NAME"] = BASE_DIR / 'db.sqlite3'
    DATABASES["default"]["TEST"]["NAME"] = BASE_DIR / 'test.sqlite3'
    DATABASES["snappea"]["NAME"] = BASE_DIR / 'snappea.sqlite3'

else:
    raise ValueError("Unknown DB", os.getenv("DB"))

# {  postponed, for starters we'll do something like SNAPPEA_ALWAYS_EAGER
# DATABASES["snappea"]["TEST"]["NAME"] = BASE_DIR / 'test.snappea.sqlite3'


# {PROTOCOL}://{PUBLIC_KEY}:{DEPRECATED_SECRET_KEY}@{HOST}{PATH}/{PROJECT_ID}
if not I_AM_RUNNING == "TEST":
    SENTRY_DSN = os.getenv("SENTRY_DSN")
    eat_your_own_dogfood(
        SENTRY_DSN,
        transport=MoreLoudlyFailingTransport,
    )

SNAPPEA = {
    "TASK_ALWAYS_EAGER": True,  # at least for (unit) tests, this is a requirement
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

    "BASE_URL": "http://bugsink:8000",  # no trailing slash
    "SITE_TITLE": "Bugsink",  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"

    # undocumented feature: this enables links to the admin interface in the header/footer. I'm not sure where the admin
    # will fit in the final version, so that's why it's not documented.
    "USE_ADMIN": True,

    # In development, I want to be able to upload broken events, so I can test their downstream rendering/processing.
    # Has the added benefit that the integration tests can run (event_samples repo contains broken events).
    "VALIDATE_ON_DIGEST": "warn",

    "KEEP_ENVELOPES": 10,

    # set MAX_EVENTS* very high to be able to do serious performance testing (which I do often in my dev environment)
    "MAX_EVENTS_PER_PROJECT_PER_5_MINUTES": 1_000_000,
    "MAX_EVENTS_PER_PROJECT_PER_HOUR": 50_000_000,
}


if not I_AM_RUNNING == "TEST":
    BUGSINK["EVENT_STORAGES"] = {
        "local_flat_files": {
            "STORAGE": "events.storage.FileEventStorage",
            "OPTIONS": {
                "basepath": os.path.join(BASE_DIR, "filestorage"),
            },
            "USE_FOR_WRITE": True,
        },
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
    # In the default config, LOGGING['handlers']['console']['filters'] = ['require_debug_true']; we mimic this here
    "filters": ['require_debug_true'],
}

if I_AM_RUNNING == "SNAPPEA":
    LOGGING['loggers']['bugsink.performance']["handlers"] = ["snappea"]
else:
    LOGGING['loggers']['bugsink.performance']["handlers"] = ["look_below_in_stream"]


# snappea development settings: see all details, and include timestamps (we have no sytemd journal here)
LOGGING["handlers"]["snappea"]["level"] = "DEBUG"
LOGGING["loggers"]["snappea"]["level"] = "DEBUG"
LOGGING["formatters"]["snappea"]["format"] = "{asctime} - {threadName} - {levelname:7} - {message}"

ALLOWED_HOSTS = deduce_allowed_hosts(BUGSINK["BASE_URL"])
