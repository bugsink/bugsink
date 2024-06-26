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
