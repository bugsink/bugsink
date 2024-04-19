import os
import signal
import json
from django.conf import settings

from . import registry

from .models import Task


def shared_task(function):
    def delayed_function(*args, **kwargs):
        if settings.SNAPPEA_TASK_ALWAYS_EAGER:
            # To ensure that args and kwargs are json-serializable in automatic tests and when using the single-server
            # setup we do these 2 .dumps calls here. The cost should be negligible in general (args/kwargs are small),
            # so even when single-server is used as a "production" server this shouldn't be a problem.
            json.dumps(args), json.dumps(kwargs)
            function(*args, **kwargs)
            # nothing is returned, because when calling x.delay(...) no result can be expected (it isn't available for
            # the non-eager case either).
            return

        # notes on the lack of immediate_atomic go here
        Task.objects.create(task_name=name, args=json.dumps(args), kwargs=json.dumps(kwargs))

        with open("/tmp/snappea.pid", "r") as f:
            # NOTE perhaps we can let systemd take a role here, it seems to do pids
            # TODO: handling of [1] no such file [2] no such process
            foreman_pid = int(f.read())
            os.kill(foreman_pid, signal.SIGUSR1)

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
