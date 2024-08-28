import logging
from django.db import migrations


logger = logging.getLogger("bugsink")


# "This migration probably shouldn't live in 'ingest', but "we have to put it somewhere".
# and that somewhere should preferably not be in a separate command.
# I also don't want to put it in an on_connect signal because that would run on each request and we need to run this
# only once (the result persists).

# Why do we use WAL? The main reason is the following snippet from the documentation (emphasis mine):
#
# > WAL mode permits simultaneous readers and writers. It can do this because changes do not overwrite the original
# > database file, but rather go into the separate write-ahead log file. That means that readers can continue to read
# > the old, original, unaltered content from the original database file at the same time that the writer is appending
# > to the write-ahead log. **In WAL mode, SQLite exhibits "snapshot isolation".** When a read transaction starts, that
# > reader continues to see an unchanging "snapshot" of the database file as it existed at the moment in time when the
# > read transaction started. Any write transactions that commit while the read transaction is active are still
# > invisible to the read transaction, because the reader is seeing a snapshot of database file from a prior moment in
# > time.
#
# The reason I want this is because it's a model for DB reads that I can wrap my head around. As a side-effect, it seems
# likely from skimming various articles on the internet and the sqlite docs that WAL actually has better performance,
# and less likelihood of deadlocks.
#
# Regarding "a model I can wrap my head around" for DB writes: we get this "for free" with SQLite: write transactions
# lock the whole DB, so they are completely serialized. This makes for easy reasoning (as long as writes are wrapped in
# transactions) at the cost of no paralellism (which we deal with by [a] focussing on keeping write transactions as
# short as possible [b] the ingest/digest distinction which provides an internal queue [c] quotas/load shedding)


def set_wal_pragma(apps, schema_editor):
    # for non-sqlite (i.e. mysql) databases, this set is simply skipped.
    if not schema_editor.connection.vendor == 'sqlite':
        logger.info('\n    Migration info: Database vendor: {}'.format(schema_editor.connection.vendor))
        logger.info('    Migration info: Skipping set_wal migration')
        return

    if schema_editor.connection.is_in_memory_db():
        logger.info('\n    Migration info: Skipping set_wal migration for in-memory database')
        return

    with schema_editor.connection.cursor() as cursor:
        # > The WAL journaling mode uses a write-ahead log instead of a rollback journal to implement transactions
        result = cursor.execute("PRAGMA journal_mode=WAL;")
        resulting_row = result.fetchone()
        if resulting_row != ("wal",):
            raise Exception(f"Failed to set WAL journaling mode, sqlite returned: { resulting_row }")


def backwards(apps, schema_editor):
    if not schema_editor.connection.vendor.startswith('sqlite'):
        logger.info('\n    Migration info: Database vendor: {}'.format(schema_editor.connection.vendor))
        logger.info('    Migration info: Skipping (backwards) migration for set_wal')
        return

    if schema_editor.connection.is_in_memory_db():
        logger.info('\n    Migration info: Skipping (backwards) set_wal migration for in-memory database')
        return

    # > The DELETE journaling mode is the normal behavior.
    schema_editor.execute("PRAGMA journal_mode=DELETE;")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
    ]

    # strictly speaking, running this migration before the others is not necessary, but it seems like the right thing to
    # first choose the journaling mode and then create the tables.
    run_before = [
        ('admin', '0001_initial'),
        ('auth', '0001_initial'),
        ('contenttypes', '0001_initial'),
        ('sessions', '0001_initial'),

        ('events', '0001_initial'),
        ('issues', '0001_initial'),
        ('projects', '0001_initial'),
        ('releases', '0001_initial'),
        ('teams', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(set_wal_pragma, backwards),
    ]
