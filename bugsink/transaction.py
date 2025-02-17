from contextlib import contextmanager
import logging
import time
from functools import partial
import types
import threading

from django.db import transaction as django_db_transaction
from django.db import DEFAULT_DB_ALIAS

performance_logger = logging.getLogger("bugsink.performance.db")

# as per https://sqlite.org/forum/forumpost/f2427b925c1669b7 (the text below is slightly improved)
#
# All DB-altering work that the threads do is wrapped in BEGIN IMMEDIATELY transactions, which thus serve as a mutex of
# sorts, because the threads cannot start a transaction when another thread is in a transaction. However, it seems that
# this mechanism does not serve as a mutex from the perspective of checkpointing. My hypothesis/understanding is that
# when thread A does a COMMIT, thread B's transaction can start. It is at that point that thread A attempts its
# checkpointing, which it cannot do because thread B has already started a new transaction.
#
# (Additional evidence for this theory, not mentioned on the internet is: in the pre-semaphore setup, I see the log for
# "BEGIN" appearing (sometimes a few miliseconds) before "IMMEDIATE" (which is when the __exit__ is complete). I
# temporarily added an extra "ABOUT TO BEGIN" log statement for clarification.
#
# Supporting evidence for this hypothesis is: when I wrap a Python lock around the transaction (which makes thread B
# wait until thread A has returned from its COMMIT), checkpointing does succeed.
#
# The immediate_semaphore is TSTTCPW to serialize writes more aggressively than just using IMMEDIATE. (For cross-process
# locking that's still no help, but [a] in the recommended setup there is barely any cross-process locking and [b] this
# lock only is only there to prevent WAL-growth, it's not for correctness (IMMEDIATE is for correctness).)
immediate_semaphore = threading.Semaphore(1)


class SemaphoreContext:
    def __enter__(self):
        if not immediate_semaphore.acquire(timeout=10):
            # "should never happen", but I'd rather have a clear error message than a silent deadlock; the timeout of 10
            # is chosen to be longer than the DB-related timeouts. i.e. when this happens it's presumably an error in
            # the locking mechanism specifically, not actually caused by the DB being busy.
            raise RuntimeError("Could not acquire immediate_semaphore")

    def __exit__(self, exc_type, exc_value, traceback):
        immediate_semaphore.release()


class SuperDurableAtomic(django_db_transaction.Atomic):
    """'super' durable because it is durable in tests as well"""

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

        super(SuperDurableAtomic, self).__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        super(SuperDurableAtomic, self).__exit__(exc_type, exc_value, traceback)


def durable_atomic(using=None, savepoint=True):
    # this is the Django 4.2 db.transaction.atomic but with durable=True by default

    # the model of "just having outer transactions" is one that I can wrap my head around, and I would like to make sure
    # it's the one I've implemented.
    if callable(using):
        return SuperDurableAtomic(DEFAULT_DB_ALIAS, savepoint, durable=True)(using)
    return SuperDurableAtomic(using, savepoint, durable=True)


def _start_transaction_under_autocommit_patched(self):
    self.cursor().execute("BEGIN IMMEDIATE")


class ImmediateAtomic(SuperDurableAtomic):
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

    ## why transactions:
    One more note that I have trouble integrating into the story-line. Django says

    > Atomicity is the defining property of database transactions.

    But this is not true. But we also care about isolation (views on the data) and about serializability (the order of
    transactions). In particular serializability (locking out other writers) is what we are after here.
    """

    # We use some ad hoc monkey-patching to implement this, relying on the fact that the _start_transaction_under_..
    # is sqlite-only, and its normal implementation is to simply execute BEGIN. The present class wraps the usual
    # enter/exit semantics with monkey-patching. auto-ignoring for non-sqlite happens because other backends do not
    # have the patched method; get_connection is thread_local, so monkey-patching is thread-safe.

    def __enter__(self):
        connection = django_db_transaction.get_connection(self.using)

        if hasattr(connection, "_start_transaction_under_autocommit"):
            connection._start_transaction_under_autocommit_original = connection._start_transaction_under_autocommit
            connection._start_transaction_under_autocommit = types.MethodType(
                _start_transaction_under_autocommit_patched, connection)

        self.t0 = time.time()
        super(ImmediateAtomic, self).__enter__()

        if connection.vendor != 'sqlite':
            # we just do a "select the first row" query on the ContentType table to make sure we have a global write
            # lock (for sqlite, this is not necessary, because BEGIN IMMEDIATE already does that). (We prefer
            # ContentType over User because of the whole users.get_user_model() thing.) `.first()` is needed to make the
            # qs actually evaluate (become non-lazy).
            #
            # Note: for a moment I considered pushing the select_for_update closer to the location where it matters
            # most, i.e. ingest, and also to tie it more closely to e.g. the project at hand. As it stands, I actually
            # like very much that we stick closely to the sqlite model for the mysql case, but we can always take this
            # road later.
            from django.contrib.contenttypes.models import ContentType
            ContentType.objects.select_for_update().order_by("pk").first()

        took = (time.time() - self.t0) * 1_000
        performance_logger.info(f"{took:6.2f}ms BEGIN IMMEDIATE, A.K.A. get-write-lock")
        self.t0 = time.time()

    def __exit__(self, exc_type, exc_value, traceback):
        super(ImmediateAtomic, self).__exit__(exc_type, exc_value, traceback)

        took = (time.time() - self.t0) * 1000
        performance_logger.info(f"{took:6.2f}ms IMMEDIATE transaction")

        connection = django_db_transaction.get_connection(self.using)
        if hasattr(connection, "_start_transaction_under_autocommit"):
            connection._start_transaction_under_autocommit = connection._start_transaction_under_autocommit_original
            del connection._start_transaction_under_autocommit_original


@contextmanager
def immediate_atomic(using=None, savepoint=True, durable=True):
    # this is the Django 4.2 db.transaction.atomic, but using ImmediateAtomic, and with durable=True by default

    # the following assertion is because "BEGIN IMMEDIATE" supposes a "BEGIN" (of a transaction), i.e. has no meaning
    # when this wrapper is not the outermost one.

    # Side-note: the parameter `savepoint` is a bit of a misnomer, it is not about "is the current thing a savepoint",
    # but rather, "are savepoints allowed inside the current context". (The former would imply that it could never be
    # combined with durable=True, which is not the case.)
    assert durable, "immediate_atomic should always be used with durable=True"

    if callable(using):
        immediate_atomic = ImmediateAtomic(DEFAULT_DB_ALIAS, savepoint, durable)(using)
    else:
        immediate_atomic = ImmediateAtomic(using, savepoint, durable)

    # https://stackoverflow.com/a/45681273/339144 provides some context on nesting context managers; and how to proceed
    # if you want to do this with an arbitrary number of context managers.
    with SemaphoreContext(), immediate_atomic:
        yield


def delay_on_commit(function, *args, **kwargs):
    django_db_transaction.on_commit(partial(function.delay, *args, **kwargs))
