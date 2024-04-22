import uuid
import os
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

        wakeup_calls_dir = os.path.join('/tmp', 'snappea')
        if not os.path.exists(wakeup_calls_dir):
            os.mkdir(wakeup_calls_dir, exist_ok=True)

        with open(os.path.join(wakeup_calls_dir, str(uuid.uuid4())), "w"):
            pass

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
