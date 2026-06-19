import time
from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Max
from django.db.models.functions import TruncHour
from django.utils import timezone

from bugsink.timed_sqlite_backend.base import different_runtime_limit
from events.models import Event
from events.sparklines import get_sparkline_range
from issues.models import Issue
from tags.models import EventTag
from tags.search import search_events

from .pftest_search import _format_query_plan


class Command(BaseCommand):
    """Internal command to inspect searched sparkline bucket query plans."""

    help = "Print timings and EXPLAIN QUERY PLAN output for searched issue sparkline buckets."

    def add_arguments(self, parser):
        parser.add_argument("issue_id")
        parser.add_argument(
            "--query",
            action="append",
            dest="queries",
            required=True,
            help="Search query to bucket. Can be passed multiple times.",
        )
        parser.add_argument(
            "--runtime-limit",
            type=float,
            default=10.0,
            help="SQLite runtime limit in seconds while executing the bucket query.",
        )
        parser.add_argument("--print-sql", action="store_true")

    def _get_bucket_qs(self, issue, q, query_start, query_end):
        return search_events(issue.project, issue, q).filter(
            digested_at__gte=query_start,
            digested_at__lt=query_end,
        ).annotate(
            bucket=TruncHour("digested_at", tzinfo=dt_timezone.utc),
        ).values("bucket").annotate(
            count=Count("id"),
            matching_digest_order=Max("digest_order"),
        ).values_list("bucket", "count", "matching_digest_order")

    def _print_query_plan(self, bucket_qs):
        sql, params = bucket_qs.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql, params)
            self.stdout.write(_format_query_plan(cursor.fetchall()))

        return sql, params

    def handle(self, *args, **options):
        issue = Issue.objects.get(id=options["issue_id"])
        now = timezone.now()
        ranges = [get_sparkline_range(now, hour_step=hour_step) for hour_step in (24, 12, 6)]
        query_start = min(start for start, _, _ in ranges)
        query_end = max(end for _, end, _ in ranges)

        self.stdout.write(f"Issue: {issue.id}")
        self.stdout.write(f"Project: {issue.project_id}")
        self.stdout.write(f"Stored events: {issue.stored_event_count:,}")
        self.stdout.write(f"Total observed events: {issue.digested_event_count:,}")
        self.stdout.write(f"Retained Event rows: {Event.objects.filter(issue=issue).count():,}")
        self.stdout.write(f"EventTag rows: {EventTag.objects.filter(issue=issue).count():,}")
        self.stdout.write(f"Bucket range: {query_start.isoformat()} to {query_end.isoformat()}")

        for q in options["queries"]:
            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write(q)
            self.stdout.write("=" * 80)

            bucket_qs = self._get_bucket_qs(issue, q, query_start, query_end)
            sql, params = self._print_query_plan(bucket_qs)

            if options["print_sql"]:
                self.stdout.write("")
                self.stdout.write(sql)
                self.stdout.write(str(params))

            t0 = time.perf_counter()
            with different_runtime_limit(options["runtime_limit"]):
                rows = list(bucket_qs)
            elapsed = time.perf_counter() - t0

            self.stdout.write(
                "Rows: %d; matching events in rows: %d; elapsed: %.4fs" %
                (len(rows), sum(row[1] for row in rows), elapsed)
            )
            self.stdout.write(f"Sample rows: {rows[:5]}")
