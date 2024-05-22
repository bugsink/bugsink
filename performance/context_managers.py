import time

from contextlib import contextmanager


@contextmanager
def time_to_logger(logger, msg):
    t0 = time.time()
    try:
        yield
    finally:
        took = (time.time() - t0) * 1000
        logger.info(f"{took:6.2f}ms {msg}")
