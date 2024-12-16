from collections import defaultdict
from pygments.lexers import _iter_lexerclasses, _fn_matches
from os.path import basename

from pygments.lexers import (
    ActionScript3Lexer, CLexer, ColdfusionHtmlLexer, CSharpLexer, HaskellLexer, GoLexer, GroovyLexer, JavaLexer,
    JavascriptLexer, ObjectiveCLexer, PerlLexer, PhpLexer, PythonLexer, RubyLexer, TextLexer, XmlPhpLexer)

_all_lexers = None


def _custom_options(clz, options):
    if clz in [PhpLexer, XmlPhpLexer]:
        options["startinline"] = True
    return options


def get_all_lexers():
    global _all_lexers
    if _all_lexers is None:
        d = defaultdict(list)
        for lexer in _iter_lexerclasses():
            for filename in lexer.filenames:
                d[filename].append(lexer)
            for filename in lexer.alias_filenames:
                d[filename].append(lexer)
        _all_lexers = MRUList(d.items())

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


def guess_lexer_for_filename(_fn, code=None, **options):
    """
    Similar to pygments' guess_lexer_for_filename, but:

    * we iterate over the lexers in order of "most recently matched".
    * we return only a single result based on filename & code

    We return None if no lexer matches the filename.

    This significantly speeds up the guessing process: when using 'vanilla' pygments, the guessing takes approximately
    5ms (note that on stacktraces there may easily be 20 frames, so this goes times 20 i.e. in the 100ms range). We can
    do it in ~.01ms. this is unsurprising, because pygments always does ~500 tests (regex calls), and we only do a few
    for the most common programming languages (fractionally above 1 on average, because you'll have only a handful in
    practice, and that handfull will typically not alternate much in a given stacktrace). (The above numbers are not
    updated for the current implementation)

    (initialization, i.e. setting the caches, takes ~.2s in both approaches)
    """

    fn = basename(_fn)

    def test(tup):
        pattern, classes = tup
        return _fn_matches(fn, pattern)

    try:
        pattern, classes = get_all_lexers().get(test)
    except ValueError:
        return None

    def get_rating(cls):
        # from pygmets/lexers/__init__'s guess_lexer_for_filename; but adapted for "cls only"; and `code` is required
        return cls.analyse_text(code)

    if len(classes) == 1:
        # optimization: if there's only one, we don't need to sort. note: guarding for 0-len is not necessary, because
        # of how we construct the lookup table (we always have at least one lexer for each pattern)
        clz = classes[0]
    else:
        classes = sorted(classes, key=get_rating)

    clz = classes[-1]
    print([(get_rating(a), a) for a in classes])

    options = _custom_options(clz, options)
    return clz(**options)


def lexer_for_platform(platform, **options):
    # We can depend on platform having been set: it's a required attribute as per Sentry's docs.
    # The LHS in the table below is a fixed list of available platforms, as per the Sentry docs.
    # The RHS is my educated guess for what these platforms map to in Pygments.

    clz = {
        "as3": ActionScript3Lexer,
        "c": CLexer,
        "cfml": ColdfusionHtmlLexer,
        "cocoa": TextLexer,  # I couldn't find the Cocoa lexer in Pygments, this will do for now.
        "csharp": CSharpLexer,
        "elixir": TextLexer,  # I couldn't find the Elixir lexer in Pygments, this will do for now.
        "haskell": HaskellLexer,
        "go": GoLexer,
        "groovy": GroovyLexer,
        "java": JavaLexer,
        "javascript": JavascriptLexer,

        # > The Sentry Native SDK is intended for C and C++. However, since it builds as a dynamic library and exposes
        # > C-bindings, it can be used by any language that supports interoperability with C, such as the Foreign
        # > Function Interface (FFI).
        # i.e. "it may be C or C++ or any other language that can call C functions", i.e. we can't reliably pick
        "native": TextLexer,
        "node": JavascriptLexer,  # I'm assuming the language is always JavaScript if the declared platform is Node.
        "objc": ObjectiveCLexer,
        "other": TextLexer,  # "other" by definition implies that nothing is known.
        "perl": PerlLexer,  # or Perl6Lexer...
        "php": PhpLexer,
        "python": PythonLexer,
        "ruby": RubyLexer,
    }[platform]
    options = _custom_options(clz, options)
    return clz(**options)
