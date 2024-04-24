from django.conf import settings


DEFAULTS = {
    "TASK_ALWAYS_EAGER": False,

    "PID_FILE": "/tmp/snappea.pid",
    "WAKEUP_CALLS_DIR": "/tmp/snappea.wakeup",

    "NUM_WORKERS": 4,
    "GRACEFUL_TIMEOUT": 10,

    "TASK_QS_LIMIT": 100,

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
        _settings.update(getattr(settings, "SNAPPEA", {}))

    return _settings
