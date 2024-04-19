from django.db.backends.signals import connection_created


def set_pragmas(sender, connection, **kwargs):
    # It appears these pragmas don't persist across connections, so we need to set them on each new connection.

    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            # Documentation (https://www.sqlite.org/pragma.html#pragma_synchronous), non-WAL removed, emphasis mine:
            #
            # > When synchronous is NORMAL (1), the SQLite database engine will still sync at the most critical moments,
            # > but less often than in FULL mode. [..]  WAL mode is safe from corruption with synchronous=NORMAL [..]
            # > WAL mode is always consistent with synchronous=NORMAL, but WAL mode does lose durability. A transaction
            # > committed in WAL mode with synchronous=NORMAL might roll back following a power loss or system crash.
            # > Transactions are durable across application crashes regardless of the synchronous setting or journal
            # > mode. **The synchronous=NORMAL setting is a good choice for most applications running in WAL mode.**
            #
            # (the default is FULL, which is the most conservative setting and one that comes with a performance cost)
            cursor.execute('PRAGMA synchronous = NORMAL;')


connection_created.connect(set_pragmas)
