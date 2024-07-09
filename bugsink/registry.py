import contextlib
import atexit
import os
import logging
from datetime import datetime, timezone

from django.conf import settings

from projects.models import Project
from events.models import Event
from issues.models import Issue
from performance.context_managers import time_to_logger
from snappea.settings import get_settings as get_snappea_settings

from .period_counter import PeriodCounter
from .app_settings import get_settings


ingest_logger = logging.getLogger("bugsink.ingest")
performance_logger = logging.getLogger("bugsink.performance.registry")


_registry = None


class PeriodCounterRegistry(object):

    def __init__(self):
        self.by_project, self.by_issue = self.load_from_scratch(
            projects=Project.objects.all(),
            issues=Issue.objects.all(),
            ordered_events=Event.objects.all().order_by('server_side_timestamp'),
            now=datetime.now(timezone.utc),
        )

    @classmethod
    def load_from_scratch(self, projects, issues, ordered_events, now):
        # create period counters for all projects and issues
        by_project = {}
        by_issue = {}

        for project in projects.iterator():
            by_project[project.id] = PeriodCounter()

        for issue in issues.iterator():
            by_issue[issue.id] = PeriodCounter()

        # load all events (one by one, let's measure the slowness of the naive implementation before making it faster)
        for event in ordered_events.iterator():
            project_pc = by_project[event.project_id]
            project_pc.inc(event.timestamp)

            issue_pc = by_issue[event.issue_id]
            issue_pc.inc(event.timestamp)

        return by_project, by_issue


class NotSingleton(Exception):
    pass


def _cleanup_pidfile():
    pid_filename = os.path.join(get_settings().INGEST_STORE_BASE_DIR, "pc_registry.pid")
    with contextlib.suppress(FileNotFoundError):
        os.remove(pid_filename)


def _ensure_singleton():
    # We ensure that the assumption that there's only one process doing ingestion (this is a requirement of our setup
    # because our in-memory pc_registry only works correctly if there's only one that takes all `.inc` calls).
    #
    # Implementation copied with modifications from to snappea/foreman.py. We construct a PID_FILENAME from
    # INGEST_STORE_BASE_DIR (that's a good place because it maps nicely to 'one place on the FS where ingestion-related
    # stuff happens).
    #
    pid_filename = os.path.join(get_settings().INGEST_STORE_BASE_DIR, "pc_registry.pid")

    # this implementation is not supposed to be bullet-proof for race conditions (nor is it cross-platform) but it
    # guards against:
    # * misconfigurations, in particular running multiple gunicorn workers when either TASK_ALWAYS_EAGER or
    #   DIGEST_IMMEDIATELY is True (in both cases ingestion happens right in the web process, and if there is more than
    #   one web process, we get multiple pc_registry instances)
    # * programming errors by the bugsink developers (non-ingesting processes calling `get_pc_registry`)

    pid = os.getpid()

    if os.path.exists(pid_filename):
        with open(pid_filename, "r") as f:
            old_pid = int(f.read())
        if os.path.exists(f"/proc/{old_pid}"):
            eager = "eager" if get_snappea_settings().TASK_ALWAYS_EAGER else "not eager"
            digest_immediately = "digest immediately" if get_settings().DIGEST_IMMEDIATELY else "digest later"
            running = settings.I_AM_RUNNING.lower()
            raise NotSingleton("Other pc_registry exists. I am '%s' in mode '%s, %s'" % (
                running, digest_immediately, eager))
        else:
            ingest_logger.warning("Stale pc_registry pid file found, removing %s", pid_filename)
            os.remove(pid_filename)

    os.makedirs(os.path.dirname(pid_filename), exist_ok=True)
    with open(pid_filename, "w") as f:
        f.write(str(pid))

    atexit.register(_cleanup_pidfile)


def get_pc_registry():
    # note: must be run inside a transaction to ensure consistency because we use .iterator()
    # https://docs.djangoproject.com/en/5.0/ref/databases/#sqlite-isolation

    global _registry
    if _registry is None:
        with time_to_logger(performance_logger, "period counter registry initialization"):
            _ensure_singleton()
            _registry = PeriodCounterRegistry()
    return _registry


def reset_pc_registry():
    # needed for tests
    global _registry
    _registry = None
    _cleanup_pidfile()
