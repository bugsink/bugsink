import logging
import requests
import platform
import json

from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from bugsink.transaction import durable_atomic, immediate_atomic
from bugsink.version import __version__
from bugsink.app_settings import get_settings

from snappea.decorators import shared_task
from snappea.settings import get_settings as get_snappea_settings

from projects.models import Project
from teams.models import Team

from .models import Installation, OutboundMessage


logger = logging.getLogger("bugsink.phonehome")


User = get_user_model()

INTERVAL = 60 * 60  # phone-home once an hour


@shared_task
def send_if_due():
    # considered: not sending if DEBUG=True. But why? Expectation is: I'm the sole user of that setting. Better send
    # also, to keep symmetry, and indirectly check whether my own phone-home still works.
    if not get_settings().PHONEHOME:
        return

    # Note on attempted_at / sent_at distinction: attempted_at is when we first tried to send the message, and sent_at
    # is when we actually sent it. This allows us to try only once an hour, as well as track whether sending succeeded.
    not_due_qs = OutboundMessage.objects.filter(
        attempted_at__gte=timezone.now() - timezone.timedelta(seconds=INTERVAL)).exists()

    with durable_atomic():
        # We check twice to see if there's any work: once in a simple read-only transaction (which doesn't block), and
        # (below) then again in the durable transaction (which can block) to actually ensure no 2 processes
        # simultaneously start the process of sending the message. This incurs the cost of 2 queries in the (less
        # common) case where the work is due, but it avoids the cost of blocking the whole DB for the (more common) case
        # where the work is not due.
        if not_due_qs:
            return

    with immediate_atomic():
        if not_due_qs:
            return

        # TODO: clean up old messages (perhaps older than 1 week)

        message = OutboundMessage.objects.create(
            # attempted_at is auto_now_add; will be filled in automatically
            message=json.dumps(_make_message_body()),
        )

    if not _send_message(message):
        return

    with immediate_atomic():
        # a fresh transaction avoids hogging the DB while doing network I/O
        message.sent_at = timezone.now()
        message.save()


def _make_message_body():
    return {
        "installation_id": str(Installation.objects.get().id),
        "version": __version__,
        "python_version": platform.python_version(),

        "settings": {
            # Settings that tell us "who you are", and are relevant in the context of licensing.
            "BASE_URL": str(get_settings().BASE_URL),
            "SITE_TITLE": get_settings().SITE_TITLE,
            "DEFAULT_FROM_EMAIL": settings.DEFAULT_FROM_EMAIL,

            # we don't have these settings yet.
            # LICENSE_KEY
            # LICENSE_NAME
            # LICENSE_EMAIL
            # LICENSE_USERS
            # LICENSE_EXPIRY
            # LICENSE_TYPE

            # Settings that tell us a bit about how Bugsink is actually deployed. Useful for support.
            "SINGLE_USER": get_settings().SINGLE_USER,
            "SINGLE_TEAM": get_settings().SINGLE_TEAM,
            "EMAIL_BACKEND": settings.EMAIL_BACKEND,
            "TASK_ALWAYS_EAGER": get_snappea_settings().TASK_ALWAYS_EAGER,
            "DIGEST_IMMEDIATELY": get_settings().DIGEST_IMMEDIATELY,
            "IS_DOCKER": settings.IS_DOCKER,
            "DATABASE_ENGINE": settings.DATABASES["default"]["ENGINE"],
        },

        "usage": {
            "user_count": User.objects.count(),
            "active_user_count": User.objects.filter(is_active=True).count(),
            "project_count": Project.objects.count(),
            "team_count": Team.objects.count(),

            # event-counts [per some interval (e.g. 24 hours)] is a possible future enhancement. We've already seen that
            # such counts are expensive though, but if _make_message_body() is pulled out of the immediate_atomic()
            # block (which is OK, since there is no need for some kind of 'transactional consistency' to register this
            # simple metadata fact), then it might be OK to add some more expensive queries here.
        },
    }


def _send_message(message):
    url = "https://www.bugsink.com/phonehome/v1/"

    def post(timeout):
        response = requests.post(url, json=json.loads(message.message), timeout=timeout)
        response.raise_for_status()

    if get_snappea_settings().TASK_ALWAYS_EAGER:
        # Doing a switch on "am I running this in snappea or not" so deep in the code somehow feels wrong, but "if it
        # looks stupid but works, it ain't stupid" I guess. The point is: when doing http requests inline I want them to
        # be fast enough not to bother your flow and never fail loudly; in the async case you have a bit more time, and
        # failing loudly (which will be picked up, or not, in the usual ways) is actually a feature.

        try:
            # 1s max wait time each hour is deemed "OK"; (counterpoint: also would be on your _first_ visit)
            post(timeout=1)
        except requests.RequestException as e:
            # This is a "soft" failure; we don't want to raise an exception, but we do want to log it.
            logger.exception("Failed to send phonehome message: %s", e)
            return False

    else:
        post(timeout=5)

    return True
