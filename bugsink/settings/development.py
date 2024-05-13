from .default import *  # noqa

import os

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


DEBUG = True

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
    "TASK_ALWAYS_EAGER": True,
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
