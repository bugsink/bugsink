from .default import *  # noqa
from .default import BASE_DIR, LOGGING, DATABASES, I_AM_RUNNING

import os

from django.utils._os import safe_join
from sentry_sdk_extensions.transport import MoreLoudlyFailingTransport

from bugsink.conf_utils import deduce_allowed_hosts, eat_your_own_dogfood, deduce_script_name

# Hide development server warning
# https://docs.djangoproject.com/en/stable/ref/django-admin/#envvar-DJANGO_RUNSERVER_HIDE_WARNING
os.environ["DJANGO_RUNSERVER_HIDE_WARNING"] = "true"


# no_bandit_expl: _development_ settings, we know that this is insecure; would fail to deploy in prod if (as configured)
# the django checks (with --check --deploy) are run.
SECRET_KEY = 'django-insecure-$@clhhieazwnxnha-_zah&(bieq%yux7#^07&xsvhn58t)8@xw'  # nosec B105
DEBUG = True


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
    DATABASES["default"]["OPTIONS"]["query_timeout"] = 0.11  # canary config: fail-fast in development.

    DATABASES["snappea"]["NAME"] = BASE_DIR / 'snappea.sqlite3'
    # canary config: fail-fast. slightly distinct value from the above to allow for eadier debugging of the timeout
    # mechanism itself. (i.e. to eyeball where the value came from)
    DATABASES["snappea"]["OPTIONS"]["query_timeout"] = 0.12

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

    # no_bandit_expl: development setting, we know that this is insecure "in theory" at least
    "PID_FILE": "/tmp/bugsink/snappea.pid",  # nosec B108
}

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_PORT = 587
EMAIL_USE_TLS = True

SERVER_EMAIL = DEFAULT_FROM_EMAIL = 'Klaas van Schelven <klaas@bugsink.com>'


BUGSINK = {
    # "MAX_EVENT_SIZE": _MEBIBYTE,
    # "MAX_EVENT_COMPRESSED_SIZE": 200 * _KIBIBYTE,
    # "MAX_ENVELOPE_SIZE": 100 * _MEBIBYTE,
    # "MAX_ENVELOPE_COMPRESSED_SIZE": 20 * _MEBIBYTE,

    "BASE_URL": "http://bugsink:8000",  # no trailing slash
    "SITE_TITLE": "Bugsink",  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"

    # undocumented feature: this enables the admin interface. I'm not sure where the admin will fit in the final
    # version, so that's why it's not documented.
    "USE_ADMIN": True,

    # In development, I want to be able to upload broken events, so I can test their downstream rendering/processing.
    # Has the added benefit that the integration tests can run (event_samples repo contains broken events).
    "VALIDATE_ON_DIGEST": "warn",

    # "KEEP_ENVELOPES": 10,
    "API_LOG_UNIMPLEMENTED_CALLS": True,

    # set MAX_EVENTS* very high to be able to do serious performance testing (which I do often in my dev environment)
    "MAX_EVENTS_PER_PROJECT_PER_5_MINUTES": 1_000_000,
    "MAX_EVENTS_PER_PROJECT_PER_HOUR": 50_000_000,
    "MAX_EVENTS_PER_PROJECT_PER_MONTH": 1_000_000_000,

    "MAX_EVENTS_PER_5_MINUTES": 1_000_000,
    "MAX_EVENTS_PER_HOUR": 50_000_000,
    "MAX_EVENTS_PER_MONTH": 1_000_000_000,

    # for development: things to tune if you want to test the the quota system
    "MAX_RETENTION_PER_PROJECT_EVENT_COUNT": None,
    "MAX_RETENTION_EVENT_COUNT": None,
    "MAX_EMAILS_PER_MONTH": 10,

    "KEEP_ARTIFACT_BUNDLES": True,  # in development: useful to preserve sourcemap uploads

    # in development we want optional features enabled to [1] play with them and [2] have the tests work
    "FEATURE_MINIDUMPS": True,
}


if not I_AM_RUNNING == "TEST":
    BUGSINK["EVENT_STORAGES"] = {
        "local_flat_files": {
            "STORAGE": "events.storage.FileEventStorage",
            "OPTIONS": {
                "basepath": safe_join(BASE_DIR, "filestorage"),
            },
        },
        "local_flat_files_br": {
            "STORAGE": "events.storage.FileEventStorage",
            "OPTIONS": {
                "basepath": safe_join(BASE_DIR, "filestorage"),
                "compression_algorithm": "br",
                "future_kwarg": "added here for testing",
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


# snappea development settings: see all details, and include timestamps (we have no systemd journal here)
LOGGING["handlers"]["snappea"]["level"] = "DEBUG"
LOGGING["loggers"]["snappea"]["level"] = "DEBUG"
LOGGING["formatters"]["snappea"]["format"] = "{asctime} - {threadName} - {levelname:7} - {message}"

# email logger: we mirror the advised logger from #86 here to debug that setting itself as well as get insight in email
# sending during development
LOGGING['loggers']['bugsink.email']['level'] = "INFO"

ALLOWED_HOSTS = deduce_allowed_hosts(BUGSINK["BASE_URL"])

# django-tailwind setting; the below allows for environment-variable overriding of the npm binary path.
NPM_BIN_PATH = os.getenv("NPM_BIN_PATH", "npm")


FORCE_SCRIPT_NAME = deduce_script_name(BUGSINK["BASE_URL"])
if FORCE_SCRIPT_NAME:
    # "in theory" a "relative" (non-leading-slash) config for STATIC_URL should just prepend [FORCE_]SCRIPT_NAME
    # automatically, but I haven't been able to get that to work reliably, https://code.djangoproject.com/ticket/34028
    # so we'll just be explicit about it.
    STATIC_URL = f"{FORCE_SCRIPT_NAME}/static/"
