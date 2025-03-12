from urllib.parse import urlparse
from contextlib import contextmanager

from django.core.management.base import BaseCommand
from django.urls import resolve
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.db import connection

from issues.models import Issue


User = get_user_model()


def x_for_parent(parents, last_parent_mentions, i, parent):
    # not quite right, but "good enough" for readable output.

    if parent == 0:
        return ""

    if last_parent_mentions[parents[parent]] > i:
        s = "|  "
    else:
        s = "   "

    return x_for_parent(parents, last_parent_mentions, i, parents[parent]) + s


def _format_query_plan(rows):
    """
    formats the query plan as sqlite3 does (indentation, tree structure)
    from a list of rows, each row being a tuple with the columns of the query plan
    the columns are: (id, parent, notused, detail)
    (e.g. (0, 0, 0, 'SEARCH TABLE issues_issue ...))
    returns a string

    example output:
    QUERY PLAN
    |--SEARCH events_event USING INDEX sqlite_autoindex_events_event_1 (id=?)
    |--LIST SUBQUERY 1
    |  `--SEARCH U0 USING INDEX tags_eventt_value_i_255b9c_idx (value_id=? AND issue_id=?)
    `--USE TEMP B-TREE FOR ORDER BY
    """
    ID, PARENT, NOTUSED, DETAIL = range(4)

    parents = {row[ID]: row[PARENT] for row in rows}
    last_parent_mentions = {}
    for i, row in enumerate(rows):
        last_parent_mentions[row[PARENT]] = i

    result = []
    for i, row in enumerate(rows):
        my_branch_chars = "`--" if last_parent_mentions[row[PARENT]] == i else "|--"

        lhs_branch_chars = x_for_parent(parents, last_parent_mentions, i, row[PARENT])

        result.append(lhs_branch_chars + my_branch_chars + row[DETAIL])

    return 'QUERY PLAN\n' + '\n'.join(result)


@contextmanager
def query_debugger(print_all):
    d = {}
    queries_i = len(connection.queries)
    yield d
    queries_j = len(connection.queries)

    print('Queries executed:', len(connection.queries) - queries_i)
    print('Total query time:', sum(float(query['time']) for query in connection.queries[queries_i:]))

    if print_all:
        interesting_queries = connection.queries[queries_i:]
    else:
        interesting_queries = [query for query in connection.queries[queries_i:] if float(query['time']) > 0.005]

    for query in interesting_queries:
        print()
        print(query['sql'])
        print('Time:', query['time'] + "s")

        explain_sql = "EXPLAIN QUERY PLAN " + query['sql']
        with connection.cursor() as cursor:
            cursor.execute(explain_sql)
            print(_format_query_plan(cursor.fetchall()))

    d['total_time'] = sum(float(query['time']) for query in connection.queries[queries_i:queries_j])
    d['total_queries'] = queries_j - queries_i


class Command(BaseCommand):
    """Internal (debugging) command to test the performance of search queries."""

    def _test_url(self, url, title, description, print_all=False):
        """
        Runs the view code that matches the given URL with a fake request; prints relevant stats
        """
        parsed_url = urlparse(url)
        view, args, kwargs = resolve(parsed_url.path)
        request = RequestFactory().get(url)
        request.user = User.objects.filter(is_superuser=True).first()

        print("\n=========================================")
        print("## " + title)
        print("=========================================")
        print(url)
        print(description)
        print()

        with query_debugger(print_all) as d:
            view(request, *args, **kwargs)

        self.total_time += d['total_time']
        self.total_queries += d['total_queries']

    def handle(self, *args, **options):
        self.total_time = 0
        self.total_queries = 0

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/last/',
            "Many-event issue, no search (fetch using last)",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
            )

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/8f8f138f-a8e8-4eeb-ad39-07945efb17af/',
            "Many-event issue, no search (fetch using specific ID)",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
        )

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/last/?q=random%3Avalue-B',
            "Many-event issue, single tag that returns 50% results",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
            )

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/last/?q=random%3Avalue-B+tag2%3Avalue-B+tag3%3Avalue-B', # noqa E501
            "Many-event issue, AND-ing the tags (50% each)",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
            )

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/51773/prev/?q=random%3Avalue-B',
            "Many-event issue, search, prev",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
            )

        self._test_url(
            '/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/events/?q=random%3Avalue-B',
            "Many-event issue, single tag that returns 50% results; event-list page",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
        )

        self._test_url(
            "/issues/issue/ae3701e3-a240-4ece-b09c-f97222116155/event/last/details/?q=trace%3Af2984643c22379983eb20f1a13529bc5", # noqa E501
            "Many-event issue, search by single-event-matching tag (trace)",
            f"{Issue.objects.get(pk='ae3701e3-a240-4ece-b09c-f97222116155').event_set.all().count()} events"
            )

        self._test_url(
            "/issues/issue/332b1e6b-6c18-4849-80c0-85af8f21438a/event/last/",
            "Few-events issue, no search (fetch using last)",
            f"{Issue.objects.get(pk='332b1e6b-6c18-4849-80c0-85af8f21438a').event_set.all().count()} events"
            )

        # idea: the many-ness of the tag-values (across the DB) should not lead to a query that evaulates them all.
        self._test_url(
            '/issues/issue/332b1e6b-6c18-4849-80c0-85af8f21438a/event/last/?q=random%3Avalue-B',
            "Few-event issue, single tag that returns 50% results",
            f"{Issue.objects.get(pk='332b1e6b-6c18-4849-80c0-85af8f21438a').event_set.all().count()} events"
            )

        print("\n=========================================")
        print("## Summary")
        print("Total time:", self.total_time)
        print("Total queries:", self.total_queries)
