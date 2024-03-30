import os

from pathlib import Path

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

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

    'tailwind',
    'theme',
    'admin_auto_filters',

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
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    'bugsink.middleware.LoginRequiredMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'sentry.middleware.proxy.DecompressBodyMiddleware',
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
    }
}


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

TIME_ZONE = 'UTC'

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


# Generic CELERY settings (i.e. no expected config per-installation)

CELERY_IGNORE_RESULT = True  # we don't use the "result" part of celery
CELERY_BROKER_CONNECTION_TIMEOUT = 2.5  # long enough for glitches, short enough to get notified about real problems


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


CELERY_BROKER_URL = 'amqp://bugsink:bugsink@localhost/'
CELERY_TASK_ALWAYS_EAGER = True

POSTMARK_API_KEY = os.getenv('POSTMARK_API_KEY')

EMAIL_HOST = 'smtp.postmarkapp.com'
EMAIL_HOST_USER = POSTMARK_API_KEY
EMAIL_HOST_PASSWORD = POSTMARK_API_KEY
EMAIL_PORT = 587
EMAIL_USE_TLS = True

SERVER_EMAIL = DEFAULT_FROM_EMAIL = 'Klaas van Schelven <klaas@vanschelven.com>'
