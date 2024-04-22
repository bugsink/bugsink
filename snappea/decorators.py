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

        if not os.path.exists(wakeup_calls_dir):
            os.mkdir(wakeup_calls_dir, exist_ok=True)

        if not os.path.exists(wakeup_file):
            with open(wakeup_file, "w"):
                pass

    # We use a random filename for wakeup_file, but because this variable is bound to the shared_task decorator it is
    # not recalculated on every call to .delay(). This has the advantage that when many wakeup signals are sent but not
    # consumed they will not fill up our wakeup_calls_dir in O(n) fashion. This filling-up could otherwise happen,
    # because the Foreman takes on some chunk of work from the DB (currently: 100 records) which may take a while to be
    # processed (especially if this value is larger than the number of workers) and the wake up signals may flood the
    # wakeup_dir in that time.
    #
    # Because the call to uuid() is stored as a local variable of a function (namely: shared_task), it is by definition
    # thread-local. (CHECK: is this really so? and is this even important?)
    wakeup_calls_dir = os.path.join('/tmp', 'snappea')
    wakeup_file = os.path.join(wakeup_calls_dir, str(uuid.uuid4()))

    name = function.__module__ + "." + function.__name__
    function.delay = delayed_function
    registry[name] = function
    return function
