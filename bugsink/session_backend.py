from django.contrib.sessions.backends.db import SessionStore as DjangoSessionStore

from .transaction import immediate_atomic


class SessionStore(DjangoSessionStore):
    """Use immediate_atomic for session saves and deletions.

    We just wrap the save and delete methods in an atomic block, so that they are committed immediately, even though
    the data they write partially originates from a different read transaction.

    This keeps Django's last-write-wins behavior for concurrent session updates, possibly with stale data: A request can
    load its session before the view and save the whole modified dictionary afterward, even though other requests wrote
    different data in the meantime.

    We accept this on the assumption that concurrent modifications to the same session are uncommon. Most requests
    only read it; writes are concentrated around login, logout, password changes/reset, and message fallback when
    messages do not fit in their cookie. Only the password-reset token is written by our own code. These are occasional
    operations, so we expect little contention within one session. Also, Django's protection against resurrecting
    sessions deleted by logout remains in place.

    Related Django tickets:
    * https://code.djangoproject.com/ticket/21608 - Special-case for logout; fixed
    * https://code.djangoproject.com/ticket/10760 - Proof of "last-write-wins" behavior; open
    * https://code.djangoproject.com/ticket/11506 - Proof of "last-write-wins" behavior; open
    """

    def save(self, must_create=False):
        with immediate_atomic(only_if_needed=True):
            return super().save(must_create=must_create)

    def delete(self, session_key=None):
        with immediate_atomic(only_if_needed=True):
            return super().delete(session_key=session_key)
