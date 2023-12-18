import time

from bugsink.period_counter import _prev_tup


# this file is the beginning of an approach to getting a handle on performance.


class passed_time(object):
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, type, value, traceback):
        self.elapsed = (time.time() - self.t0) * 1_000  # miliseconds is a good unit for timeing things


def print_thoughts_about_prev_tup():
    v = (2020, 1, 1, 10, 10)
    with passed_time() as t:
        for i in range(1_000):
            v = _prev_tup(v)

    print(f"""1_000 iterations of _prev_tup in {t.elapsed:.3f}ms. The main thing we care about is not this little
private helper though, but PeriodCounter.inc(). Let's test that next.

On testing: I noticed variations of a factor 2 even running these tests only a couple of times. For now I picked the
slow results for a check in.

""")


print_thoughts_about_prev_tup()
