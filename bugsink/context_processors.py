from collections import namedtuple

from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.contrib.auth.models import AnonymousUser

from bugsink.app_settings import get_settings, CB_ANYBODY
from bugsink.transaction import durable_atomic

from snappea.settings import get_settings as get_snappea_settings
from snappea.models import Task

from phonehome.models import Installation

SystemWarning = namedtuple('SystemWarning', ['message', 'ignore_url'])


FREE_VERSION_WARNING = mark_safe(
    """This is the free version of Bugsink; usage is limited to a single user for local development only.
    Using this software in production requires a
    <a href="https://www.bugsink.com/#pricing" target="_blank" class="font-bold text-slate-800">paid licence</a>.""")

EMAIL_BACKEND_WARNING = mark_safe(
    """Email is not set up, emails won't be sent. To get the most out of Bugsink, please
    <a href="https://www.bugsink.com/docs/settings/#email" target="_blank" class="font-bold text-slate-800">set up
    email</a>.""")


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

    WARNING = SystemWarning((f"Snappea has {task_count} tasks in the queue, the oldest being {oldest_task_age}s old. "
                             f"It may be either overwhelmed, blocked, not running, or misconfigured."), None)

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

    system_warnings = []

    if settings.EMAIL_BACKEND in [
            'django.core.mail.backends.console.EmailBackend',
            'bugsink.email_backends.QuietConsoleEmailBackend'] and not installation.silence_email_system_warning:

        if getattr(request, "user", AnonymousUser()).is_superuser:
            ignore_url = reverse("silence_email_system_warning")
        else:
            # not a superuser, so can't silence the warning. I'm applying some heuristics here;
            # * superusers (and only those) will be able to deal with this (have access to EMAIL_BACKEND)
            # * better to still show (though not silencable) the message to non-superusers.
            # this will not always be so, but it's a good start.
            ignore_url = None

        system_warnings.append(SystemWarning(EMAIL_BACKEND_WARNING, ignore_url))

    return {
        # Note: no way to actually set the license key yet, so nagging always happens for now.
        'site_title': get_settings().SITE_TITLE,
        'registration_enabled': get_settings().USER_REGISTRATION == CB_ANYBODY,
        'app_settings': get_settings(),
        'system_warnings': system_warnings + get_snappea_warnings(),
    }


def logged_in_user_processor(request):
    return {
        # getattr, because if there's a failure "very early" in the request handling, we don't have an AnonymousUser
        'logged_in_user': getattr(request, "user", AnonymousUser()),
    }
