"""Check application entry points for writes outside immediate_atomic during SQLite tests."""

from contextlib import contextmanager
from functools import wraps
from unittest.mock import patch

from django.core.handlers.base import BaseHandler
from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.test import TestCase as DjangoTestCase
from django.test.runner import DiscoverRunner
from django.test.utils import iter_test_cases

from .transaction import ImmediateAtomic


@contextmanager
def require_write_transaction():
    """Reject writes outside immediate_atomic while a request, command handler or task runs.

    SQLite's PRAGMA query_only applies to a connection: ON makes SQLite reject writes, including writes in implicit
    transactions and durable_atomic. The test runner temporarily turns it OFF while ImmediateAtomic is active.
    """
    application_connection = connections["default"]
    if application_connection.vendor != "sqlite":
        yield
        return

    # If we're already inside an immediate_atomic block, don't do anything. This can happen if a task/view/command is
    # called from application code; in practice/typically: in eagerly executed tasks.
    if any(isinstance(block, ImmediateAtomic) for block in application_connection.atomic_blocks):
        yield
        return

    application_connection.ensure_connection()  # Django opens connections lazily; the PRAGMA needs an open one.
    sqlite_connection = application_connection.connection
    pragma_query_only_to_restore = sqlite_connection.execute("PRAGMA query_only").fetchone()[0]
    try:
        sqlite_connection.execute("PRAGMA query_only=ON")
        yield
    finally:
        assert application_connection.connection is sqlite_connection, (
            "Application code closed or replaced the database connection during a transaction write check"
        )
        sqlite_connection.execute(f"PRAGMA query_only={pragma_query_only_to_restore}")


def check_write_transactions(function):
    # An already checked function needs no second wrapper.
    if getattr(function, "_checks_write_transactions", False):
        return function

    @wraps(function)
    def checked(*args, **kwargs):
        with require_write_transaction():
            return function(*args, **kwargs)

    checked._checks_write_transactions = True
    return checked


class TransactionTestRunner(DiscoverRunner):
    """Require DB writes in requests, tasks and commands to be in an immediate_atomic block.

    Hooked up like so:

    * The runner wraps Django's request handling and command handlers by patching BaseHandler.get_response and
      BaseCommand.__init__ for the duration of the test run.

    * shared_task wraps tasks with check_write_transactions only when settings.I_AM_RUNNING == "TEST".
    """

    def build_suite(self, test_labels=None, **kwargs):
        suite = super().build_suite(test_labels, **kwargs)
        for test in iter_test_cases(suite):
            if isinstance(test, DjangoTestCase):
                test_class = type(test)
                raise RuntimeError(
                    f"{test_class.__module__}.{test_class.__qualname__} inherits django.test.TestCase, "
                    "which hides transaction boundaries. Use TransactionTestCase25251 for database tests "
                    "or SimpleTestCase for tests without database access."
                )
        return suite

    def run_tests(self, test_labels, **kwargs):
        original_ImmediateAtomic__enter__ = ImmediateAtomic.__enter__
        original_ImmediateAtomic__exit__ = ImmediateAtomic.__exit__
        original_BaseCommand__init__ = BaseCommand.__init__
        original_BaseHandler__get_response = BaseHandler.get_response

        def ImmediateAtomic__enter__(atomic_block):
            application_connection = transaction.get_connection(atomic_block.using)
            if application_connection.alias != "default" or application_connection.vendor != "sqlite":
                return original_ImmediateAtomic__enter__(atomic_block)

            application_connection.ensure_connection()  # The PRAGMA needs an open SQLite connection.
            sqlite_connection = application_connection.connection
            pragma_query_only_to_restore = sqlite_connection.execute("PRAGMA query_only").fetchone()[0]
            if not pragma_query_only_to_restore:
                return original_ImmediateAtomic__enter__(atomic_block)

            atomic_block._pragma_query_only_to_restore = pragma_query_only_to_restore
            sqlite_connection.execute("PRAGMA query_only=OFF")
            try:
                return original_ImmediateAtomic__enter__(atomic_block)
            except BaseException:
                sqlite_connection.execute(f"PRAGMA query_only={atomic_block._pragma_query_only_to_restore}")
                del atomic_block._pragma_query_only_to_restore
                raise

        def ImmediateAtomic__exit__(atomic_block, *args):
            # Restore query_only before calling the original __exit__, which may run on_commit callbacks.
            # Those callbacks run outside the transaction and must use their own immediate_atomic for writes.
            # This doesn't break COMMIT.
            if hasattr(atomic_block, "_pragma_query_only_to_restore"):
                application_connection = transaction.get_connection(atomic_block.using)
                sqlite_connection = application_connection.connection
                sqlite_connection.execute(f"PRAGMA query_only={atomic_block._pragma_query_only_to_restore}")
                del atomic_block._pragma_query_only_to_restore

            return original_ImmediateAtomic__exit__(atomic_block, *args)

        def BaseCommand__init__(command, *args, **kwargs):
            original_BaseCommand__init__(command, *args, **kwargs)

            if command.handle.__module__.startswith("django."):
                # Django's own commands (including migrations and fixture loading) don't use our transaction model.
                return

            command.handle = check_write_transactions(command.handle)

        def BaseHandler__get_response(handler, request):
            # This wraps the whole view, including middleware. This might expose Django pain, but that's the point.
            with require_write_transaction():
                return original_BaseHandler__get_response(handler, request)

        with (
            patch.object(ImmediateAtomic, "__enter__", ImmediateAtomic__enter__),
            patch.object(ImmediateAtomic, "__exit__", ImmediateAtomic__exit__),
            patch.object(BaseCommand, "__init__", BaseCommand__init__),
            patch.object(BaseHandler, "get_response", BaseHandler__get_response),
        ):
            return super().run_tests(test_labels, **kwargs)
