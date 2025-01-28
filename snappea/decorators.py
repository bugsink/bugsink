import logging
import json

from performance.context_managers import time_to_logger

from . import registry
from .models import Task, wakeup_server
from .settings import get_settings
from .utils import add_task_kwargs

performance_logger = logging.getLogger("bugsink.performance.snappea")


def shared_task(function):
    def delayed_function(*args, **kwargs):
        if get_settings().TASK_ALWAYS_EAGER:
            # To ensure that args and kwargs are json-serializable in automatic tests and when using the single-server
            # setup we do these 2 .dumps calls here. The cost should be negligible in general (args/kwargs are small),
            # so even when single-server is used as a "production" server this shouldn't be a problem.
            json.dumps(args), json.dumps(kwargs)
            function(*args, **kwargs)
            # nothing is returned, because when calling x.delay(...) no result can be expected (it isn't available for
            # the non-eager case either).
            return

        with time_to_logger(performance_logger, "Snappea Task.create()"):
            # No need for a transaction: we just write something (not connected to any other object, and we will never
            # touch it again). Counterpoint: if we'd have a transaction, we could distinguish between "wait for write
            # lock" and "actually write".
            kwargs.update(add_task_kwargs())
            Task.objects.create(task_name=name, args=json.dumps(args), kwargs=json.dumps(kwargs))

            # not necessary: `connections["snappea"].close()`; Django does this at the end of the request and the
            # foreman's thread cleanup code does it for worker threads.

        wakeup_server()

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
