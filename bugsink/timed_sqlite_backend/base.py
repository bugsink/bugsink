import logging
from collections import namedtuple
from copy import deepcopy
import time
from contextlib import contextmanager
from django.conf import settings
from threading import local

from django.db import DEFAULT_DB_ALIAS
from django.db.backends.sqlite3.base import (
    DatabaseWrapper as UnpatchedDatabaseWrapper, SQLiteCursorWrapper as UnpatchedSQLiteCursorWrapper,
)


logger = logging.getLogger("bugsink")

# We disinguish between the default runtime limit for a connection (set in the settings) and a runtime limit set by the
# "with different_runtime_limit" idiom, i.e. temporarily. The reason we need to distinguish these two concepts (and keep
# track of their values) explicitly, and provide the fallback getter mechanism (cm if available, otherwise
# connection-default) rather than have the program's stack determine this implicitly, is that we do not generally know
# the moment the connection default value is set. It's set when a connection is needed, which may in fact be _after_
# some CMs have already been called. (For nested CMs we do not have this problem, so we just keep track of "old" values
# inside the CMs as they live on the Python stack)
Runtimes = namedtuple("Runtimes", ["default_for_connection", "override_by_cm"])
NoneRuntimes = Runtimes(None, None)

thread_locals = local()


def _set_runtime_limit(using, is_default_for_connection, seconds):
    if using is None:
        using = DEFAULT_DB_ALIAS

    if not hasattr(thread_locals, "runtime_limits"):
        thread_locals.runtime_limits = {}

    if is_default_for_connection:
        thread_locals.runtime_limits[using] = Runtimes(
            default_for_connection=seconds,
            override_by_cm=thread_locals.runtime_limits.get(using, NoneRuntimes).override_by_cm,
        )
    else:
        thread_locals.runtime_limits[using] = Runtimes(
            default_for_connection=thread_locals.runtime_limits.get(using, NoneRuntimes).default_for_connection,
            override_by_cm=seconds,
        )


def _get_runtime_limit(using):
    if using is None:
        using = DEFAULT_DB_ALIAS

    if not hasattr(thread_locals, "runtime_limits"):
        # somewhat overly defensive, since you'd always pass through the DatabaseWrapper which sets at least once.
        thread_locals.runtime_limits = {}

    tup = thread_locals.runtime_limits.get(using, NoneRuntimes)
    return tup.override_by_cm if tup.override_by_cm is not None else tup.default_for_connection


def allow_long_running_queries():
    """Set a global flag to allow long-running queries. Useful for one-off commands, where slowness is expected."""
    # we use is_default_for_connection=False here, to make this act like a "context manager which doesn't reset", i.e.
    # what we do here takes precedence over the connection default value.
    _set_runtime_limit(using=None, is_default_for_connection=False, seconds=float("inf"))


@contextmanager
def different_runtime_limit(seconds, using=None):
    if using is None:
        using = DEFAULT_DB_ALIAS

    old = _get_runtime_limit(using=using)
    _set_runtime_limit(using=using, is_default_for_connection=False, seconds=seconds)

    try:
        yield
    finally:
        _set_runtime_limit(using=using, is_default_for_connection=False, seconds=old)


@contextmanager
def limit_runtime(alias, conn, query=None, params=None):
    # query & params are only used for logging purposes; they are not used to actually limit the runtime.
    start = time.time()

    def check_time():
        if time.time() > start + _get_runtime_limit(alias):
            return 1

        return 0

    # Set the progress handler to check the time; 10_000 is the number of SQLite VM instructions between invocations;
    # Simon Willison's experiments in Datasette suggest to use 1_000 here; but I don't care about precision so much
    # (it's just a final backstop) and I want to avoid the calls-into-Python (expensive!) as much as possible so I pick
    # a higher value.
    conn.set_progress_handler(check_time, 10_000)

    yield

    if time.time() > start + _get_runtime_limit(alias) + 0.01:
        # https://sqlite.org/forum/forumpost/fa65709226 to see why we need this.
        #
        # Doing an actual timeout _now_ doesn't achieve anything (the goal is generally to avoid things taking too long,
        # once you're here only time-travel can help you). So `logger.error()` rather than `raise OperationalError`.
        #
        # + 0.05s to avoid false positives like so: the query completing in exactly runtime_limit with the final check
        # coming a fraction of a second later (0.01s is assumed to be well on the "avoid false positives" side of the
        # trade-off)
        took = time.time() - start
        logger.error("limit_runtime miss (%.3fs): %s %s", took, query, params)

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

    def __init__(self, settings_dict, alias=DEFAULT_DB_ALIAS):
        settings_dict = deepcopy(settings_dict)
        configured_runtime_limit = settings_dict.get("OPTIONS", {}).pop("query_timeout", 5.0)
        _set_runtime_limit(using=alias, is_default_for_connection=True, seconds=configured_runtime_limit)

        super().__init__(settings_dict, alias=alias)

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
        return self.connection.cursor(factory=get_sqlite_cursor_wrapper(self.alias))


def get_sqlite_cursor_wrapper(alias):
    if alias is None:
        alias = DEFAULT_DB_ALIAS

    class SQLiteCursorWrapper(UnpatchedSQLiteCursorWrapper):

        def execute(self, query, params=None):
            if settings.I_AM_RUNNING == "MIGRATE":
                # migrations in Sqlite are often slow (drop/recreate tables, etc); so we don't want to limit them
                return super().execute(query, params)

            with limit_runtime(alias, self.connection, query=query, params=params):
                return super().execute(query, params)

        def executemany(self, query, param_list):
            if settings.I_AM_RUNNING == "MIGRATE":
                # migrations in Sqlite are often slow (drop/recreate tables, etc); so we don't want to limit them
                return super().executemany(query, param_list)

            with limit_runtime(alias, self.connection, query=query, params=param_list):
                return super().executemany(query, param_list)

    return SQLiteCursorWrapper
