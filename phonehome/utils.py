from functools import wraps

from django.utils import timezone
from bugsink.transaction import durable_atomic

from .models import OutboundMessage


INTERVAL = 60 * 60  # phone-home at most once an hour


def phone_home_is_due():
    # Note on attempted_at / sent_at distinction: attempted_at is when we first tried to send the message, and sent_at
    # is when we actually sent it. This allows us to try only once an hour, as well as track whether sending succeeded.
    return not OutboundMessage.objects.filter(
        attempted_at__gte=timezone.now() - timezone.timedelta(seconds=INTERVAL)).exists()


def phone_home(view):
    from .tasks import send_if_due
    # I need a way to cron-like run tasks that works for the setup with and without snappea. When using snappea this
    # would be straight-forward (although snappea has no support for 'cron' _yet_). In ALWAYS_EAGER setups, you'd need
    # _some_ location to do a "poor man's cron" check. Server-start would be the first thing to consider, but how to do
    # this across gunicorn, debugserver, and possibly even non-standard (for Bugsink) wsgi servers? Better go the "just
    # pick some requests to do the check" route. I've picked "home", "project view" and "event detail" because these are
    # [a] assumed to be somewhat regularly visited [b] there's no transaction logic in it, which leaves space for
    # transaction-logic in the phone-home task itself and [c] some alternatives are a no-go (ingestion: on a tight
    # budget; login: not visited when a long-lived session is active).
    #
    # having chosen the solution for the non-snappea case, I got the crazy idea of using it for the snappea case too,
    # i.e. just put a .delay() here and let the config choose. Not so crazy though, because [a] saves us from new
    # features in snappea, [b] we introduce a certain symmetry of measurement between the 2 setups, i.e. the choice of
    # lazyness does not influence counting and [c] do I really want to get pings for sites where nobody visits the 3
    # most relevant pages of the project?

    @wraps(view)
    def inner(request, *args, **kwargs):
        # This decorator must be the outermost one (guaranteeing no other transaction logic is running).
        with durable_atomic():
            # We check twice to see if there's any work: once in a simple read-only transaction (which doesn't block),
            # and then again (in send_if_due) in the immediate transaction (which can block) to actually ensure no two
            # processes simultaneously start the process of sending the message. This incurs the cost of 2 queries in
            # the (less common) case where the work is due, but it avoids the cost of blocking the whole DB for the
            # (more common) case where the work is not due.
            is_due = phone_home_is_due()

        # The actual task kick-off must happen after the durable_atomic block has exited. In TASK_ALWAYS_EAGER mode,
        # .delay() executes inline, and send_if_due() itself starts its own transactions; doing that while still inside
        # the read-side durable_atomic above would nest durable transactions in the same thread.
        if is_due:
            send_if_due.delay()

        return view(request, *args, **kwargs)

    return inner
