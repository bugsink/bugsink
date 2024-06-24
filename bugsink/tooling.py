# "Tooling" as in "useful while developing"

from django.db import connection
from contextlib import contextmanager


@contextmanager
def show_queries():
    pre = len(connection.queries)
    yield
    for query in connection.queries[pre:]:
        print(query['sql'])
