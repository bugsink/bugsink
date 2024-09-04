from django.conf import settings


DEFAULTS = {
    "TASK_ALWAYS_EAGER": False,

    "PID_FILE": "/tmp/snappea.pid",
    "WAKEUP_CALLS_DIR": "/tmp/snappea.wakeup",

    "NUM_WORKERS": 4,

    # Workaholic mode: I will not stop, even when I'm told to, until _all_ of my tasks are done. This was built for the
    # case of Docker but might just be useful outside it. Consider:
    #
    # * snappea and the server are in the same container, and communicate via an sqlite queue (file) in the container.
    # * containers are supposed to be disposable; the message queue will be disposed of when the container is; the
    #   ingested (but not yet digested) events in the /tmp/ dir will be too, by the way.
    # * snappea may get a TERM signal because either the container is being stopped, or when the server exits (via
    #   monofy).
    #
    # Given the above, it's better for snappea to do all the work it can before it gets killed the drastic way when
    # Docker gets impatient, than to quickly shut down and leave the server with a bunch of unprocessed events. This is
    # what the "workaholic" mode is for.
    #
    # Note about scenario that we don't deal with 100%: on docker-stop, the sigterm is sent to both processes at the
    # same time. Gunicorn may then take some time to fully shut down while still serving requests, and in that
    # time-taking enqueue new tasks; such tasks would not be picked up, even in workaholic mode. An improvement could be
    # to shut down in-order, but for now this is in "perfectionism" territory for us.
    "WORKAHOLIC": False,

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
