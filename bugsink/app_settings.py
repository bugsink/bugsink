# approach as in snappea/settings.py
# alternative would be: just put "everything" in the big settings.py (or some mix-using-imports version of that).
# but for now I like the idea of keeping the bugsink-as-an-app stuff separate from the regular Django/db/global stuff.
from contextlib import contextmanager

from django.conf import settings


_KIBIBYTE = 1024
_MEBIBYTE = 1024 * _KIBIBYTE


DEFAULTS = {
    "DIGEST_IMMEDIATELY": True,

    # MAX* below mirror the (current) values for the Sentry Relax
    "MAX_EVENT_SIZE": _MEBIBYTE,
    "MAX_EVENT_COMPRESSED_SIZE": 200 * _KIBIBYTE,  # Note: this only applies to the deprecated "store" endpoint.
    "MAX_ENVELOPE_SIZE": 100 * _MEBIBYTE,
    "MAX_ENVELOPE_COMPRESSED_SIZE": 20 * _MEBIBYTE,

    # I don't think Sentry specifies this one, but we do: given the spec 8KiB should be enough by an order of magnitude.
    "MAX_HEADER_SIZE": 8 * _KIBIBYTE,
}


class AttrLikeDict(dict):
    def __getattr__(self, item):
        return self[item]


_settings = None


def get_settings():
    global _settings
    if _settings is None:
        _settings = AttrLikeDict()
        _settings.update(DEFAULTS)
        _settings.update(getattr(settings, "BUGSINK", {}))

    return _settings


@contextmanager
def override_settings(**new_settings):
    global _settings
    old_settings = _settings
    _settings = AttrLikeDict()
    _settings.update(old_settings)
    for k in new_settings:
        assert k in old_settings, "Unknown setting (likely error in tests): %s" % k
    _settings.update(new_settings)
    yield
    _settings = old_settings
