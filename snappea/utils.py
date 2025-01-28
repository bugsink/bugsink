from contextlib import contextmanager
import importlib

from .settings import get_settings


def add_task_kwargs():
    """Hook for extending Task kwargs"""

    if not hasattr(add_task_kwargs, "func"):
        # the configured function is cached on add_task_kwargs itself
        hook = get_settings().HOOK_ADD_TASK_KWARGS
        module_name, function_name = hook.rsplit('.', 1)
        module = importlib.import_module(module_name)
        add_task_kwargs.func = getattr(module, function_name)

    return add_task_kwargs.func()


def run_task_context(task_args, task_kwargs):
    """Hook for running a task in a context; the task's args and kwargs are passed for optional pre-processing"""

    if not hasattr(add_task_kwargs, "func"):
        # the configured function is cached on run_task_context itself
        hook = get_settings().HOOK_RUN_TASK_CONTEXT
        module_name, function_name = hook.rsplit('.', 1)
        module = importlib.import_module(module_name)
        run_task_context.func = getattr(module, function_name)

    return run_task_context.func(task_args, task_kwargs)


def dont_add_anything():
    # no-op impl of add_task_kwargs
    return {}


@contextmanager
def no_context(task_args, task_kwargs):
    # no-op impl of run_task_context
    yield
