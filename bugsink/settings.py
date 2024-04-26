from copy import deepcopy
import os
import sys

from pathlib import Path

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from django.utils.log import DEFAULT_LOGGING

from debug_toolbar.middleware import show_toolbar

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-$@clhhieazwnxnha-_zah&(bieq%yux7#^07&xsvhn58t)8@xw'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]  # SECURITY WARNING: also make production-worthy

INTERNAL_IPS = [
    "127.0.0.1",
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'debug_toolbar',
    'tailwind',
    'theme',
    'admin_auto_filters',

    'snappea',
    'compat',
    'projects',
    'releases',
    'ingest',
    'issues',
    'events',
    'alerts',

    'performance',
]

TAILWIND_APP_NAME = 'theme'

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",

    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    'bugsink.middleware.LoginRequiredMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'bugsink.middleware.PerformanceStatsMiddleware',
]

ROOT_URLCONF = 'bugsink.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / "templates",
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                'bugsink.context_processors.useful_settings_processor',
                'bugsink.context_processors.logged_in_user_processor',
                'projects.context_processors.user_projects_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'bugsink.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / os.getenv("DATABASE_NAME", 'db.sqlite3'),
        'TEST': {
            # Specifying a NAME here makes it so that sqlite doesn't run in-memory. This is what we want, because we
            # want our tests to be as similar to the real thing as possible.
            "NAME": BASE_DIR / os.getenv("DATABASE_NAME", 'test.sqlite3'),
        },
        'OPTIONS': {
            # the "timeout" option here is passed to the Python sqlite3.connect() translates into the busy_timeout
            # PRAGMA in SQLite.  (5000ms is just a starting point; we can adjust it after we have some data, or even
            # make it configurable)
            'timeout': 5,  # this is the default (as per the Python sqlite3 package); we're just being explicit
        },
    },
    "snappea": {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / os.getenv("DATABASE_NAME", 'snappea.sqlite3'),
        # 'TEST': {  postponed, for starters we'll do something like SNAPPEA_ALWAYS_EAGER
        'OPTIONS': {
            'timeout': 5,
        },
    },
}


DATABASE_ROUTERS = ("bugsink.dbrouters.SeparateSnappeaDBRouter",)


LOGIN_REDIRECT_URL = "/"

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Europe/Amsterdam'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field
# no support for uuid in this setting yet (https://code.djangoproject.com/ticket/32577) so we leave it as-is
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


def show_toolbar_for_queryparam(request):
    if "__debug__" not in request.path and not request.GET.get("debug", ""):
        return False
    return show_toolbar(request)


DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": show_toolbar_for_queryparam,
}


LOGGING = deepcopy(DEFAULT_LOGGING)
LOGGING['loggers']['bugsink'] = {
    "level": "INFO",
    "handlers": ["console"],
}

# Snappea Logging
LOGGING["formatters"]["snappea"] = {
    "format": "{asctime} - {threadName} - {levelname:7} - {message}",
    "style": "{",
}

LOGGING["handlers"]["snappea"] = {
    "level": "DEBUG" if DEBUG else "INFO",
    "class": "logging.StreamHandler"
}

LOGGING["handlers"]["snappea"]["formatter"] = "snappea"

LOGGING['loggers']['snappea'] = {
    "level": "DEBUG" if DEBUG else "INFO",
    "handlers": ["snappea"],
}

# TODO sys.argv checking: how do I want to deal with it in my final config setup?
if sys.argv[1:2] == ['runsnappea']:
    for logger in LOGGING['loggers'].values():
        logger["handlers"] = ["snappea"]


# ###################### SERVER-MODE SETTINGS #################

BUGSINK_DIGEST_IMMEDIATELY = True

# ###################### MOST PER-SITE CONFIG BELOW THIS LINE ###################


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

BASE_URL = "http://bugsink:9000"  # no trailing slash
SITE_TITLE = "Bugsink"  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"

SNAPPEA = {
    "TASK_ALWAYS_EAGER": True,
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
}
