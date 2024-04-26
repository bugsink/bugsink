import logging
import time
from functools import partial
import types
from django.db import transaction as django_db_transaction
from django.db import DEFAULT_DB_ALIAS

performance_logger = logging.getLogger("bugsink.performance.db")


def _start_transaction_under_autocommit_patched(self):
    self.cursor().execute("BEGIN IMMEDIATE")


class ImmediateAtomic(django_db_transaction.Atomic):
    """
    Sqlite specific (for other DBs this is simply ignored).

    immediate_atomic allows us to begin atomic transactions using BEGIN IMMEDIATE instead of the default BEGIN. The
    sqlite docs explain a context in which this is useful:

    > Another example: X starts a read transaction using BEGIN and SELECT, then Y makes a changes to the database using
    > UPDATE. Then X tries to make a change to the database using UPDATE. The attempt by X to escalate its transaction
    > from a read transaction to a write transaction fails with an SQLITE_BUSY_SNAPSHOT error because the snapshot of
    > the database being viewed by X is no longer the latest version of the database. If X were allowed to write, it
    > would fork the history of the database file, which is something SQLite does not support. [..]

    > **If X starts a transaction that will initially only read but X knows it will eventually want to write and does
    > not want to be troubled with possible SQLITE_BUSY_SNAPSHOT errors that arise because another connection jumped
    > ahead of it in line, then X can issue BEGIN IMMEDIATE to start its transaction instead of just an ordinary
    > BEGIN.** The BEGIN IMMEDIATE command goes ahead and starts a write transaction, and thus blocks all other writers.
    > If the BEGIN IMMEDIATE operation succeeds, then no subsequent operations in that transaction will ever fail with
    > an SQLITE_BUSY error.

    Django 5.1 will introduce the option to configure BEGIN IMMEDIATE, but only globally. This is not what we want,
    because it unnecessarily escalates read-only-transactions into write-transactions.

    https://github.com/django/django/pull/17760

    PoC of the problem (which indeed goes away by converting to immediate); run in 2 separate shells to demonstrate it:

    from time import sleep
    from django.contrib.auth.models import User
    from django.db import transaction

    @transaction.atomic()
    def read_sleep_write():
        print("I am going to read")
        user = User.objects.first()
        print("I am going to sleep")
        sleep(5)
        print("I am going to write")
        user.save() # no need to actually change the user, as long as we run a write query
    """

    # We use some ad hoc monkey-patching to implement this, relying on the fact that the _start_transaction_under_..
    # is sqlite-only, and its normal implementation is to simply execute BEGIN. The present class wraps the usual
    # enter/exit semantics with monkey-patching. auto-ignoring for non-sqlite happens because other backends do not
    # have the patched method; get_connection is thread_local, so monkey-patching is thread-safe.

    def __enter__(self):
        connection = django_db_transaction.get_connection(self.using)

        # Like the superclass check, but more strict for the case of "in tests"
        if (self.durable and connection.atomic_blocks):
            if not connection.atomic_blocks[-1]._from_testcase:
                raise RuntimeError("A durable atomic block cannot be nested within another atomic block.")

            # We do not allow nesting of durable atomic blocks in tests. If it's important enough to run in atomic mode,
            # it's important enough to be tested as such. I just spent 2 hours debugging a test that was failing because
            # of this.
            raise RuntimeError("A durable atomic block cannot be nested -- not even in tests.")

        if hasattr(connection, "_start_transaction_under_autocommit"):
            connection._start_transaction_under_autocommit_original = connection._start_transaction_under_autocommit
            connection._start_transaction_under_autocommit = types.MethodType(
                _start_transaction_under_autocommit_patched, connection)

        self.t0 = time.time()
        super(ImmediateAtomic, self).__enter__()
        took = (time.time() - self.t0) * 1_000
        performance_logger.info(f"    {took:6.2f}ms BEGIN IMMEDIATE, A.K.A. get-write-lock' ↴")
        self.t0 = time.time()

    def __exit__(self, exc_type, exc_value, traceback):
        super(ImmediateAtomic, self).__exit__(exc_type, exc_value, traceback)

        took = (time.time() - self.t0) * 1000
        performance_logger.info(f"    {took:6.2f}ms IMMEDIATE transaction' ↴")

        connection = django_db_transaction.get_connection(self.using)
        if hasattr(connection, "_start_transaction_under_autocommit"):
            connection._start_transaction_under_autocommit = connection._start_transaction_under_autocommit_original
            del connection._start_transaction_under_autocommit_original


def immediate_atomic(using=None, savepoint=True, durable=True):
    # this is the Django 4.2 db.transaction.atomic, but using ImmediateAtomic, and with durable=True by default

    # the following assertion is because "BEGIN IMMEDIATE" supposes a "BEGIN" (of a transaction), i.e. has no meaning in
    # the context of savepoints.
    assert durable, "immediate_atomic should always be used with durable=True"

    if callable(using):
        return ImmediateAtomic(DEFAULT_DB_ALIAS, savepoint, durable)(using)
    else:
        return ImmediateAtomic(using, savepoint, durable)


def delay_on_commit(function, *args, **kwargs):
    django_db_transaction.on_commit(partial(function.delay, *args, **kwargs))
