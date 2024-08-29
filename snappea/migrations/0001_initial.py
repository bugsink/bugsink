import logging
from django.db import migrations


logger = logging.getLogger("snappea")


def set_wal_pragma(apps, schema_editor):
    # even though we're currently on "sqlite only" for the snappea database, we take the forward-looking approach of at
    # least having the escape hatch for other DBs:
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

    operations = [
        migrations.RunPython(set_wal_pragma, backwards),
    ]
