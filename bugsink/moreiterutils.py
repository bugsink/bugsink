from itertools import islice


def map_N_until(f, until, onemore=False):
    """
    maps f over the natural numbers until some value `until` is reaced, e.g.:

    >>> list(map_N_until(lambda x: x * x, 55))
    [0, 1, 4, 9, 16, 25, 36, 49]
    """
    n = 0
    result = f(n)
    while result < until:
        yield result
        n += 1
        result = f(n)
    if onemore:
        yield result


def pairwise(it):
    """
    >>> list(pairwise(range(0)))
    []
    >>> list(pairwise(range(1)))
    []
    >>> list(pairwise(range(2)))
    [(0, 1)]
    >>> list(pairwise(range(3)))
    [(0, 1), (1, 2)]
    """
    it = iter(it)
    try:
        prev = next(it)
    except StopIteration:
        return
    for current in it:
        yield (prev, current)
        prev = current


def tuplewise(iterable):
    """
    >>> list(tuplewise(range(4)))
    [(0, 1), (2, 3)]
    """
    i = iter(iterable)
    while True:
        try:
            yield next(i), next(i)
        except StopIteration:
            return


def batched(iterable, n):
    # itertools.batched was introduced in Python 3.12, but it's "roughly equivalent" to this:

    # batched('ABCDEFG', 3) → ABC DEF G
    if n < 1:
        raise ValueError('n must be at least one')
    iterator = iter(iterable)
    while batch := tuple(islice(iterator, n)):
        yield batch
