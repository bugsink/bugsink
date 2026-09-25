import time

from contextlib import contextmanager

from django.db import connection


class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        return execute(sql, params, many, context)


@contextmanager
def count_queries():
    counter = QueryCounter()
    with connection.execute_wrapper(counter):
        yield counter


@contextmanager
def time_to_logger(logger, msg):
    t0 = time.time()
    try:
        yield
    finally:
        took = (time.time() - t0) * 1000
        logger.info(f"{took:6.2f}ms {msg}")


class TimeAndQueryCount:
    def __init__(self):
        self.took = None
        self.count = None


@contextmanager
def time_and_query_count():
    result = TimeAndQueryCount()
    t0 = time.time()
    with count_queries() as query_counter:
        try:
            yield result
        finally:
            result.took = (time.time() - t0) * 1000
            result.count = query_counter.count


class Time:
    def __init__(self):
        self.took = None


@contextmanager
def time_it():
    result = Time()
    t0 = time.time()
    try:
        yield result
    finally:
        result.took = (time.time() - t0) * 1000
