from copy import deepcopy
import os
import sys

from pathlib import Path

from django.utils.log import DEFAULT_LOGGING


# We have a single file for our default settings, and expect (if they use the singleserver setup) the end-users to
# configure their setup using a single bugsink_conf.py also. To be able to have (slightly) different settings for e.g.
# logging for various commands, we expose a variable I_AM_RUNNING that can be used to determine what command is being
# run. We use (potentially fragile) sys.argv checks to determine what command is being run. For now "it works, don't
# fix it"
if sys.argv[1:2] == ['runsnappea']:
    I_AM_RUNNING = "SNAPPEA"
elif sys.argv[1:2] == ['test']:
    I_AM_RUNNING = "TEST"
elif sys.argv[1:2] == ['migrate']:
    I_AM_RUNNING = "MIGRATE"
elif [s.endswith("gunicorn") for s in sys.argv[:1]] == [True]:
    I_AM_RUNNING = "GUNICORN"
else:
    I_AM_RUNNING = "OTHER"


# Used for reporting / debugging purposes. The default docker conf template overrides this accordingly.
IS_DOCKER = False

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# To allow using this file without any bugsink_conf.py overrides, we get some variables from the environment. Because
# the expected use-case of this file is using the `from bugsink.settings.default import *` idiom, which implies that
# variables may very well be defined explicitly in a bugsink_conf.py or similar explicit settings file, we cannot
# enforce the existance of environment variables, so we always use os.getenv with a sane fallback.

# The fallback here is such that Django will fail to start if no SECRET_KEY is (eventually) defined, which is the goal.
SECRET_KEY = os.getenv("SECRET_KEY", "")

DEBUG = False
DEBUG_CSRF = "USE_DEBUG"  # i.e. use the value of DEBUG for this setting (useful when DEBUG is set later)

# Various proxy-related settings (default.py: no proxy)
USE_X_REAL_IP = False
USE_X_FORWARDED_FOR = False
X_FORWARDED_FOR_PROXY_COUNT = 0


# Replacing "*" with your actual hostname forms an extra layer of security if your proxy/webserver is misconfigured.
# The default (production) create-conf template does this for you.
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    'tailwind',  # As currently set up, this is also needed in production (templatetags)
    'admin_auto_filters',
]

BUGSINK_APPS = [
    'bsmain',
    'phonehome',
    'users',
    'theme',
    'snappea',
    'compat',
    'teams',
    'projects',
    'releases',
    'ingest',
    'issues',
    'events',
    'tags',
    'alerts',

    'performance',
]

INSTALLED_APPS += BUGSINK_APPS

AUTH_USER_MODEL = "users.User"

TAILWIND_APP_NAME = 'theme'

MIDDLEWARE = [
    'bugsink.middleware.SetRemoteAddrMiddleware',
    'bugsink.middleware.DisallowChunkedMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'verbose_csrf_middleware.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    'bugsink.middleware.LoginRequiredMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # NOTE: _most_ useful while building Bugsink; in the singleserver production setup the timings/counts of this
    # middleware are not logged to a visible location; and this feature is undocumented. However, it _could_ prove
    # useful in such contexts too, so I'm not going to put it behind a conditional.
    'bugsink.middleware.PerformanceStatsMiddleware',
]

# Config of verbose_csrf_middleware.CsrfViewMiddleware: For Bugsink, there's never any intentional cross-scheme POSTing
# going on. In that case "wrong scheme" always just means "Django's confused about is_secure", and we want to point
# people in the right direction (i.e. fix your proxy's X-Forwarded-Proto)
VERBOSE_CSRF_REASON_SCHEME_MISMATCH = "(wrong scheme); fix your proxy's X-Forwarded-Proto"


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
            # This is the thing that used to be called "TEMPLATE_DEBUG". We set it to True to have the template code
            # context (filename in the stacktrace, offending and surrounding lines) available in our stacktraces when
            # dogfooding. This does not expose anything when 'regular DEBUG' is False. (the docs say "If it is True, the
            # fancy error page will display a detailed report for any exception raised during template rendering."; this
            # already hints at "if there is no fancy error page nothing new will be displayed" and this is indeed so (I
            # checked).
            'debug': True,
        },
    },
]

WSGI_APPLICATION = 'bugsink.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'bugsink.timed_sqlite_backend',
        'NAME': os.getenv("DATABASE_PATH", 'db.sqlite3'),
        'TEST': {
            # Specifying a NAME here makes it so that sqlite doesn't run in-memory. This is what we want, because we
            # want our tests to be as similar to the real thing as possible.
            "NAME": os.getenv("TEST_DATABASE_PATH", 'test.sqlite3'),
        },
        'OPTIONS': {
            # the "timeout" option here is passed to the Python sqlite3.connect() translates into the busy_timeout
            # PRAGMA in SQLite.  (5000ms is just a starting point; we can adjust it after we have some data, or even
            # make it configurable)
            'timeout': 5,  # this is the default (as per the Python sqlite3 package); we're just being explicit
        },
    },
    "snappea": {
        'ENGINE': 'bugsink.timed_sqlite_backend',
        'NAME': os.getenv("SNAPPEA_DATABASE_PATH", 'snappea.sqlite3'),
        # 'TEST': {  postponed, for starters we'll do something like SNAPPEA_ALWAYS_EAGER
        'OPTIONS': {
            'timeout': 5,
        },
    },
}


DATABASE_ROUTERS = ("bugsink.dbrouters.SeparateSnappeaDBRouter",)

# This is the default, but we're being explicit. In our recommended setup (sqlite) we assume a low cost for reconnecting
# to the DB, but a potential high cost ("checkpoint starvation") for keeping connections open.
#
# For not-as-recommended setups (mysql) we're OK with "one connection per request" too, even though the arguments laid
# out in the above don't apply as much. (This might change after research)
CONN_MAX_AGE = 0


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

# > Instead of only picking up files collected into STATIC_ROOT, find and serve files in their original directories
# > using Django’s “finders” API. [..] It’s also possible to use this setting in production, avoiding the need to run
# > the collectstatic command during the build, so long as you do not wish to use any of the caching and compression
# > features provided by the storage backends.
#
# Reasons to enable this in production:
#
# * Simplicity-as-a-core-value: yet another step we can remove from the install/upgrade process
# * We don't use the mentioned features (caching, compression)
# * The performance-impact of this setting only hits the GUI, which is the least performance-sensitive part anyway
WHITENOISE_USE_FINDERS = True

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field
# no support for uuid in this setting yet (https://code.djangoproject.com/ticket/32577) so we leave it as-is
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


SILENCED_SYSTEM_CHECKS = [
    "security.W003",  # Complaint about lack of "django.middleware.csrf.CsrfViewMiddleware", but we have our own version

    # in recommended setups we implement HSTS and SSL redirect at the proxy level, so we silence these checks
    "security.W004",  # SECURE_HSTS_SECONDS
    "security.W008",  # SECURE_SSL_REDIRECT
]

# Specifies a timeout in seconds for blocking operations like the connection attempt. We set this to 5 seconds to avoid
# hanging the entire application (or snappea when the workers fill up) when the SMTP server is down/unreachable.
EMAIL_TIMEOUT = 5


LOGGING = deepcopy(DEFAULT_LOGGING)

if I_AM_RUNNING != "TEST":
    # Django's standard logging has LOGGING['handlers']['console']['filters'] = ['require_debug_true']; our app is
    # configured (by default at least) to just spit everything on stdout, especially in production. stdout is picked up
    # by e.g. gunicorn, and we can "take it from there". We don't do this when running tests, because tests are run with
    # DEBUG=False and we don't want the visual pollution.
    LOGGING['handlers']['console']['filters'] = []

# Top-level bugsink logger
LOGGING['loggers']['bugsink'] = {
    "level": "INFO",
    "handlers": ["console"],
}

# Performance logging is hidden by default, but it can be enabled by adding a handler to the logger.
LOGGING['loggers']['bugsink.performance'] = {
    "level": "INFO",
    "handlers": [],
    "propagate": False,
}

# Snappea Logging
LOGGING["formatters"]["snappea"] = {
    "format": "{threadName} - {levelname:7} - {message}",
    "style": "{",
}

LOGGING["handlers"]["snappea"] = {
    "level": "INFO",
    "class": "logging.StreamHandler",
    "formatter": "snappea",
}

LOGGING['loggers']['snappea'] = {
    "level": "INFO",
    "handlers": ["snappea"],
}


if I_AM_RUNNING == "SNAPPEA":
    # We set all handlers to the snappea handler in this case: this way the things that are logged inside individual
    # workers show up with the relevant worker-annotations (i.e. threadName).
    for logger in LOGGING['loggers'].values():
        if "handlers" in logger and "console" in logger["handlers"]:
            logger["handlers"] = ["snappea"]
