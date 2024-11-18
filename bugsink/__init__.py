from django.db.backends.signals import connection_created
from django.contrib.auth.management.commands.createsuperuser import Command as CreateSuperUserCommand


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
            #
            # Note: while searching for the reason .wal files were kept around, the execution of out-of-transaction SQL
            # became a suspect briefly. I tried to push this into the transaction, but that fails ("Safety level may not
            # be changed inside a transaction") and it seemed that this particular query was not at fault anyhow.
            cursor.execute('PRAGMA synchronous = NORMAL;')


connection_created.connect(set_pragmas)


# Monkey-patch the createsuperuser command with more clear instructions
def _get_input_message(self, field, default=None):
    # I don't think I want to commit to the below yet, leaving it here for now
    # if field.verbose_name == 'Username':
    #     return "Username (use your email address):"

    if field.verbose_name == 'email address':
        return "Email (alerts/password-reset): "
    return unpatched_get_input_message(self, field, default)


unpatched_get_input_message = CreateSuperUserCommand._get_input_message
CreateSuperUserCommand._get_input_message = _get_input_message
