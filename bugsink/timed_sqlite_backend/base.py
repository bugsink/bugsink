import time
from contextlib import contextmanager
from django.conf import settings

from django.db.backends.sqlite3.base import (
    DatabaseWrapper as UnpatchedDatabaseWrapper, SQLiteCursorWrapper as UnpatchedSQLiteCursorWrapper,
)


_runtime_limit = 5.0


def allow_long_running_queries():
    """Set a global flag to allow long-running queries. Useful for one-off commands, where slowness is expected."""
    global _runtime_limit
    _runtime_limit = float("inf")


@contextmanager
def different_runtime_limit(seconds):
    global _runtime_limit
    old = _runtime_limit
    _runtime_limit = seconds

    try:
        yield
    finally:
        _runtime_limit = old


@contextmanager
def limit_runtime(conn):
    global _runtime_limit

    start = time.time()

    def check_time():
        if time.time() > start + _runtime_limit:
            return 1

        return 0

    # Set the progress handler to check the time; 10_000 is the number of SQLite VM instructions between invocations;
    # Simon Willison's experiments in Datasette suggest to use 1_000 here; but I don't care about precision so much
    # (it's just a final backstop) and I want to avoid the calls-into-Python (expensive!) as much as possible so I pick
    # a higher value.
    conn.set_progress_handler(check_time, 10_000)

    yield

    conn.set_progress_handler(None, 0)


class PrintOnClose(object):
    def __init__(self, conn):
        self.conn = conn

    def __setattr__(self, item, value):
        if item == "conn":
            return super().__setattr__(item, value)
        return setattr(self.conn, item, value)

    def __getattr__(self, item):
        return getattr(self.conn, item)

    def __hasattr__(self, item):
        return hasattr(self.conn, item)

    def close(self):
        print("Connection closed", id(self.conn))
        self.conn.close()


class DatabaseWrapper(UnpatchedDatabaseWrapper):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # This makes the cursor act like a debug cursor (storing queries) even when DEBUG=False. We need this in
        # PerformanceStatsMiddleware to provide a query-count. We expect the number of such-stored queries to be small
        # (negligible memory impact) because Bugsink doesn't do many queries generally. But strictly speaking we could
        # say that this should only be turned on when the result is actually used, i.e. when performance logging is
        # enabled.
        self.force_debug_cursor = True

    # def get_new_connection(self, conn_params):
    #     result = super().get_new_connection(conn_params)
    #     import threading
    #     print("Connection created", conn_params["database"], id(result), threading.current_thread().name)
    #     return PrintOnClose(result)

    def create_cursor(self, name=None):
        return self.connection.cursor(factory=SQLiteCursorWrapper)


class SQLiteCursorWrapper(UnpatchedSQLiteCursorWrapper):

    def execute(self, query, params=None):
        if settings.I_AM_RUNNING == "MIGRATE":
            # migrations in Sqlite are often slow (drop/recreate tables, etc); so we don't want to limit them
            return super().execute(query, params)

        with limit_runtime(self.connection):
            return super().execute(query, params)

    def executemany(self, query, param_list):
        if settings.I_AM_RUNNING == "MIGRATE":
            # migrations in Sqlite are often slow (drop/recreate tables, etc); so we don't want to limit them
            return super().executemany(query, param_list)

        with limit_runtime(self.connection):
            return super().executemany(query, param_list)
