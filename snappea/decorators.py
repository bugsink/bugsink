import os
import signal
import json

from . import registry

from .models import Pea


def shared_task(function):
    def delayed_function(*args, **kwargs):
        if False:  # TODO Eager impl
            # To ensure that args and kwargs are json-serializable in automatic tests and when using the single-server
            # setup we do these 2 .dumps calls here. The cost should be negligible in general (args/kwargs are small),
            # so even when single-server is used as a "production" server this shouldn't be a problem.
            json.dumps(args), json.dumps(kwargs)
            function(*args, **kwargs)

        # notes on the lack of immediate_atomic go here
        Pea.objects.create(task_name=name, args=json.dumps(args), kwargs=json.dumps(kwargs))

        with open("/tmp/snappea.pid", "r") as f:
            # NOTE perhaps we can let systemd take a role here, it seems to do pids
            # TODO: handling of [1] no such file [2] no such process
            foreman_pid = int(f.read())
            os.kill(foreman_pid, signal.SIGUSR1)

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
