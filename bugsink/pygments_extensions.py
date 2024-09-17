from pygments.lexers import _iter_lexerclasses, _fn_matches
from os.path import basename


_all_lexers = None


def get_all_lexers():
    global _all_lexers
    if _all_lexers is None:
        _all_lexers = MRUList(_iter_lexerclasses())
    return _all_lexers


class MRUList(object):
    """
    Is this called a MRUList in the literature? I don't know. I'm calling it that because it is a list, ordered by the
    most recently "used", where "used" is defined to be "the caller said that this is the thing they were looking for.
    """

    def __init__(self, iterable):
        self._list = list(iterable)

    def get(self, test):
        """test: a function that takes one argument and returns a boolean. it represents 'I was looking for this'."""

        # we iterate in reversed order because .pop() and .append() are O(1) at the end of the list.
        # reversed(range()) is "not expensive": empirically: next(reversed(range(10**99)))

        for i in reversed(range(len(self._list))):
            if test(self._list[i]):
                result = self._list.pop(i)
                self._list.append(result)
                return result

        raise ValueError("No item in the list matched the test")


def guess_lexer_for_filename(_fn, **options):
    """
    Similar to pygments' guess_lexer_for_filename, but:

    * we iterate over the lexers in order of "most recently matched".
    * we return only a single result based on filename.
    * we don't have the "code" argument.

    We return None if no lexer matches the filename.

    This significantly speeds up the guessing process: when using 'vanilla' pygments, the guessing takes approximately
    5ms (note that on stacktraces there may easily be 20 frames, so this goes times 20 i.e. in the 100ms range). We can
    do it in ~.01ms. this is unsurprising, because pygments always does ~500 tests (regex calls), and we only do a few
    for the most common programming languages (fractionally above 1 on average, because you'll have only a handful in
    practice, and that handfull will typically not alternate much in a given stacktrace).

    (initialization, i.e. setting the caches, takes ~.2s in both approaches)
    """

    fn = basename(_fn)

    def test(lexer):
        for filename in lexer.filenames:
            if _fn_matches(fn, filename):
                return True

        for filename in lexer.alias_filenames:
            if _fn_matches(fn, filename):
                return True

        return False

    try:
        return get_all_lexers().get(test)(**options)
    except ValueError:
        return None
