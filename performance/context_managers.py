import time

from contextlib import contextmanager

from django.db import connection


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
    pre = len(connection.queries)
    t0 = time.time()
    try:
        yield result
    finally:
        result.took = (time.time() - t0) * 1000
        result.count = len(connection.queries) - pre


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
