from datetime import timedelta

from django.utils import timezone
from django.utils.safestring import mark_safe

from bugsink.app_settings import get_settings, CB_ANYBODY
from bugsink.transaction import durable_atomic

from snappea.settings import get_settings as get_snappea_settings
from snappea.models import Task

from phonehome.models import Installation


FREE_VERSION_WARNING = mark_safe(
    """This is the free version of Bugsink; usage is limited to a single user for local development only.
    Using this software in production requires a
    <a href="https://www.bugsink.com/#pricing" target="_blank" class="font-bold text-slate-800">paid licence</a>.""")


def get_snappea_warnings():
    # We warn in either of 2 cases, as documented per-case.

    if get_snappea_settings().TASK_ALWAYS_EAGER:
        # In TASK_ALWAYS_EAGER mode, there is no expectation that snappea runs, so there should be no warning either.
        return []

    with durable_atomic(using="snappea"):
        task_count = Task.objects.all().count()
        if task_count == 0:
            # No tasks, no warnings.
            return []

        oldest_task_age = (timezone.now() - Task.objects.all().order_by('created_at').first().created_at).seconds

    WARNING = (f"Snappea has {task_count} tasks in the queue, the oldest being {oldest_task_age}s old. It may be "
               f"either overwhelmed, blocked, not running, or misconfigured.")

    # 1. "a lot" of tasks in the backlog.
    # We have a backlog because spikes are always to be expected, and dealing with them in a backlog is the feature that
    # makes the server reliably able to handle them. So why would we warn about the backlog actually being used? Well,
    # if there are "enough" (A.K.A. "a lot") of items in the backlog, you might be confused "why isn't this showing up?"
    # 10s of confusion is a nice cut-off after which a banner should unconfuse you, and with 30 events per second (safe
    # assumption given well-documented measurements) this is 300 events. Also: assumed to be rare enough to not
    # over-warn.
    if task_count > 300:
        return [WARNING]

    # 2. "a few", but _stale_ tasks in the backlog.
    # If there are some (not a lot, but >0) items in the backlog, but they seem "stale", we warn too. Hard to come up
    # with a precise definition of "stale", but we can say that if the oldest task is older than 5 seconds, people may
    # start wondering why it's not happening. (whether that is being caused by backlogging or misconfiguration, in
    # either case the warning is useful)". (An even better measure for low task_counts would be: if the last _picked-up_
    # task is longer than some time ago, but we don't register picked-up time because we delete tasks in that case). For
    # now, that's not complexity I'm willing to introduce, so we stick with the arbitrary 5s threshold.
    if oldest_task_age > 5:
        return [WARNING]

    return []


def useful_settings_processor(request):
    # name is misnomer, but "who cares".

    installation = Installation.objects.get()

    nag_7 = installation.created_at < timezone.now() - timedelta(days=7)
    nag_30 = installation.created_at < timezone.now() - timedelta(days=30)

    # (First version of "should I nag" logic): nag only after considerable time to play with the app, and for "some
    # indication" that you're using this in production (the simplest such indication is that you've configured a
    # BASE_URL that's not localhost). Subject to change.
    system_warnings = [FREE_VERSION_WARNING] if nag_30 and 'localhost' not in get_settings().BASE_URL else []

    return {
        # Note: no way to actually set the license key yet, so nagging always happens for now.
        'site_title': get_settings().SITE_TITLE + (" (non-production use)" if nag_7 else ""),
        'registration_enabled': get_settings().USER_REGISTRATION == CB_ANYBODY,
        'app_settings': get_settings(),
        'system_warnings': system_warnings + get_snappea_warnings(),
    }


def logged_in_user_processor(request):
    return {
        # getattr, because if there's a failure "very early" in the request handling, we don't have an AnonymousUser
        'logged_in_user': getattr(request, "user", None),
    }
