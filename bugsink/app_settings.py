# approach as in snappea/settings.py
# alternative would be: just put "everything" in the big settings.py (or some mix-using-imports version of that).
# but for now I like the idea of keeping the bugsink-as-an-app stuff separate from the regular Django/db/global stuff.
import os
from contextlib import contextmanager

from django.conf import settings
from bugsink.utils import assert_


_KIBIBYTE = 1024
_MEBIBYTE = 1024 * _KIBIBYTE


# CB means "create by"
CB_ANYBODY = "CB_ANYBODY"
CB_MEMBERS = "CB_MEMBERS"
CB_ADMINS = "CB_ADMINS"
CB_NOBODY = "CB_NOBODY"


_PORT = os.environ.get("PORT", "8000")


DEFAULTS = {
    "BASE_URL": f"http://localhost:{_PORT}",  # no trailing slash
    "SITE_TITLE": "Bugsink",  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"

    # Users, teams, projects
    # if True, there is only one user, and all projects are owned by that user; this is somewhat implied by
    # USER_REGISTRATION: CB_NOBODY, but I'd rather be even more explicit than that. e.g. SINGLE_USER obviously implies
    # that project members are not a thing, but USER_REGISTRATION: CB_NOBODY might still mean "you can create users in
    # the DB/AD/whatever, which could then be added to projects".
    "SINGLE_USER": False,

    "USER_REGISTRATION": CB_MEMBERS,  # who can register new users. default: members, i.e. any user can invite others
    "USER_REGISTRATION_VERIFY_EMAIL": True,
    "USER_REGISTRATION_VERIFY_EMAIL_EXPIRY": 3 * 24 * 60 * 60,  # 7 days

    # if True, there is only one team, and all projects are in that team
    "SINGLE_TEAM": False,
    "TEAM_CREATION": CB_MEMBERS,  # who can create new teams. default: members, which means "any member of the site"

    # System inner workings:
    "VALIDATE_ON_DIGEST": "none",  # other legal values are "warn" and "strict"
    "KEEP_ENVELOPES": 0,  # set to a number to store that many; 0 means "store none". This is for debugging.
    "API_LOG_UNIMPLEMENTED_CALLS": False,  # if True, log unimplemented API calls; see #153
    "KEEP_ARTIFACT_BUNDLES": False,  # if True, artifact bundles are kept in the database on-upload (for debugging)

    # MAX* below mirror the (current) values for the Sentry Relay
    "MAX_EVENT_SIZE": _MEBIBYTE,
    "MAX_ATTACHMENT_SIZE": 100 * _MEBIBYTE,
    "MAX_EVENT_COMPRESSED_SIZE": 200 * _KIBIBYTE,  # Note: this only applies to the deprecated "store" endpoint.
    "MAX_ENVELOPE_SIZE": 100 * _MEBIBYTE,
    "MAX_ENVELOPE_COMPRESSED_SIZE": 20 * _MEBIBYTE,

    # Bugsink-specific limits:
    # The default values are 1_000, 5_000, 1M respectively; which corresponds to ~6%, ~2.7%, .8% of the total capacity
    # of 50/s (ingestion) on low-grade hardware that I measured.
    "MAX_EVENTS_PER_PROJECT_PER_5_MINUTES": 1_000,
    "MAX_EVENTS_PER_PROJECT_PER_HOUR": 5_000,
    "MAX_EVENTS_PER_PROJECT_PER_MONTH": 1_000_000,

    "MAX_EVENTS_PER_5_MINUTES": 1_000,
    "MAX_EVENTS_PER_HOUR": 5_000,
    "MAX_EVENTS_PER_MONTH": 1_000_000,

    "MAX_EMAILS_PER_MONTH": None,  # None means "no limit"; for non-None values, the quota is per calendar month

    "MAX_RETENTION_PER_PROJECT_EVENT_COUNT": None,  # None means "no limit"
    "MAX_RETENTION_EVENT_COUNT": None,  # None means "no limit"

    # I don't think Sentry specifies this one, but we do: given the spec 8KiB should be enough by an order of magnitude.
    "MAX_HEADER_SIZE": 8 * _KIBIBYTE,

    # Locations of files & directories:
    # no_bandit_expl: the usage of this path (via get_filename_for_event_id) is protected with `b108_makedirs`
    "INGEST_STORE_BASE_DIR": "/tmp/bugsink/ingestion",  # nosec
    "EVENT_STORAGES": {},

    # Security:
    "MINIMIZE_INFORMATION_EXPOSURE": False,
    "PHONEHOME": True,
    "USE_ADMIN": False,

    # Feature flags:
    "FEATURE_MINIDUMPS": False,  # minidumps are experimental/early-stage and likely a DOS-magnet; disabled by default
}


class AttrLikeDict(dict):
    def __hasattr__(self, item):
        return item in self

    def __getattr__(self, item):
        # attribute errors are to be understood at the call site; as they are for regular object's missing attributes.
        __tracebackhide__ = True

        try:
            return self[item]
        except KeyError:
            # "from None": this is so directly caused by the KeyError that cause and effect are the same and cause must
            # be hidden.
            raise AttributeError(item) from None


_settings = None


def _sanitize(settings):
    """ 'sanitize' the settings, i.e. fixes common mistakes in the settings. """

    if settings["BASE_URL"].endswith("/"):
        settings["BASE_URL"] = settings["BASE_URL"][:-1]

    if settings["SINGLE_USER"]:
        # this is implemented as a "hard imply". Pro: 'it just works' even when configurations are half-baked; con: may
        # be confusing if you run into the "I thought I set that like so" case. On balance: I'd rather "just fix it"
        # than raise some warning/error and have people deal with that.
        settings["SINGLE_TEAM"] = True
        settings["USER_REGISTRATION"] = CB_NOBODY
        settings["TEAM_CREATION"] = CB_NOBODY


def get_settings():
    global _settings
    if _settings is None:
        _settings = AttrLikeDict()
        _settings.update(DEFAULTS)
        _settings.update(getattr(settings, "BUGSINK", {}))

        _sanitize(_settings)

    return _settings


@contextmanager
def override_settings(**new_settings):
    global _settings
    old_settings = _settings
    _settings = AttrLikeDict()
    _settings.update(old_settings)
    for k in new_settings:
        assert_(k in old_settings, "Unknown setting (likely error in tests): %s" % k)
    _settings.update(new_settings)
    yield
    _settings = old_settings
