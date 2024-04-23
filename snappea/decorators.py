import os
import json
from django.conf import settings

from . import registry, thread_uuid

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

        # No need for a transaction: we just write something (not connected to any other object, and we will never touch
        # it again).
        Task.objects.create(task_name=name, args=json.dumps(args), kwargs=json.dumps(kwargs))

        wakeup_calls_dir = os.path.join('/tmp', 'snappea')
        wakeup_file = os.path.join(wakeup_calls_dir, thread_uuid)

        if not os.path.exists(wakeup_calls_dir):
            os.mkdir(wakeup_calls_dir, exist_ok=True)

        if not os.path.exists(wakeup_file):
            with open(wakeup_file, "w"):
                pass

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
