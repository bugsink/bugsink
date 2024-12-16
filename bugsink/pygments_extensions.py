"""
Pygments has the following limitations:

1. Bad guessing mechanisms (especially for snippets)
2. Generally bad support for snippets.

Still, I think it's what we have in the Python world, so I'm just extending around the limitations; (mostly [1])

"""
from collections import defaultdict
from pygments.lexers import _iter_lexerclasses, _fn_matches, HtmlLexer, HtmlDjangoLexer
from pygments.lexer import DelegatingLexer

from os.path import basename

from pygments.lexers import (
    ActionScript3Lexer, CLexer, ColdfusionHtmlLexer, CSharpLexer, HaskellLexer, GoLexer, GroovyLexer, JavaLexer,
    JavascriptLexer, ObjectiveCLexer, PerlLexer, PhpLexer, PythonLexer, RubyLexer, TextLexer, XmlPhpLexer,
)

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
            for pattern in lexer.filenames:
                d[pattern].append(lexer)
            for pattern in lexer.alias_filenames:
                d[pattern].append(lexer)
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


def guess_lexer_for_filename(_fn, platform, code=None, **options):
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

    filename = basename(_fn)

    def test(tup):
        pattern, classes = tup
        return _fn_matches(filename, pattern)

    try:
        pattern, classes = get_all_lexers().get(test)
    except ValueError:
        return None

    clz = choose_lexer_for_pattern(pattern, classes, filename, code, platform)
    if clz is None:
        return None

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


def choose_lexer_for_pattern(pattern, classes, filename, code, platform):
    """
    This function chooses a lexer from the list of Lexers that Pygments associates with a given filename pattern.

    Pygments' Lexer.analyse_text is basically useless for us: generally poor quality, and depending on full-file code
    samples (we have 11-line snippets only). We choose to ignore that function and any pygments function that makes use
    of it, replacing it with the current function. The upside is: this gives us a lot of control. Also upside: once
    we're at this point we typically have to pick from a handful (max observed: 9) of lexers.

    How we pick:

    * If Pygments associates exactly one Lexer, we simply take Pygments' suggestion. (720 patterns)
    * For ~70 patterns, there is not a single Lexer associated. This is where this function's heuristics come into play.

    We take a quite conservative approach in disambiguating: the fallback if we don't manage to pick is to just use
    "platform", which will usually be quite good.

    The idea here is that a Stacktrace (which is what we're dealing with here) is typically a single-language
    artifact, and the expectation is that SDKs encode which language that is in the "platform" attr. The cases of
    mixed-language stacktraces are actually the rarity, presumably related to transpiling/templating and such.
    Emperically: the only _real_ case I've observed in the wild where the current function breaks a tie is: picking
    between Html template lexers (in particular: picking Django). (the fact that Bugsink is also Django skews this)

    In any case, I'd rather add cases to this function as needed ("complaint-driven development") than have some big
    ball of potentially very fragile tie-in with pygments' logic (note: Pygments has some 500 lexers, the vast majority
    of which will not ever show up, simply because no SDK exists for it). In short: the breakage of missing cases is
    expected to be much easier to reason about than that of "too much magic".

    (counts of cases are from Pygments==2.16.1, end-of-2024)
    """
    if len(classes) == 1:
        # the non-heuristic case (nothing to choose) doubles as an optimization. (0-len check not needed because the
        # lookup table is constructed by looping over the existing Lexers)
        return classes[0]

    # heuristics below

    if pattern in ["*.html", "*.htm", "*.xhtml", "*.xslt", "*.html"]:  # (deduced from 'if HtmlLexer in classes')
        if platform == "python":
            return HtmlDjangoLexer  # which is actually the Django/Jinja lexer (which makes it an even better guess)

        # alternative solution: look at the code, deduce from there. but I reasoned: the only reason html code appears
        # on the stacktrace is if it's a template. Your SDK must do some explicit work to get it there. And the only
        # such case I know is the one of the DjangoIntegration.
        # if re.search(r'\{%.*%\}', code) is not None or re.search(r'\{\{.*\}\}', code) is not None:

        # The other HtmlLexer-like ones are: EvoqueHtmlLexer, HtmlGenshiLexer, HtmlPhpLexer, HtmlSmartyLexer,
        # LassoHtmlLexer, RhtmlLexer, VelocityHtmlLexer
        return HtmlLexer

    return None


def get_most_basic_if_exists(classes):
    # UNUSED; kept for reference.
    #
    # The reasoning here was: maybe we can just pick the "simplest" of a list of Lexers, which is somehow the base-case.
    # But the following are deductions I'm unwilling to make (among probably others):
    #
    # *.cp => ComponentPascalLexer' from [(ComponentPascalLexer', 4), (CppLexer', 5)]
    # *.incl => LassoLexer' from [(LassoLexer', 4), (LassoHtmlLexer', 14), (LassoXmlLexer', 14)]
    # *.xsl => XmlLexer' from [(XmlLexer', 4), (XsltLexer', 5)]
    #
    # In the end, unused b/c the general "don't build complex logic on top of Pygments, instead fix based on observed
    # need"

    def basicness(clz):
        return len(clz.mro()) + (10 if DelegatingLexer in clz.mro() else 0)  # 10 is 'arbitrary high' for non-basic

    classes = sorted(classes, key=basicness)
    x_classes = sorted([(basicness(clz), clz) for clz in classes], key=lambda tup: tup[0])

    best_basicness = x_classes[0][0]
    best_ones = [clz for basicness, clz in x_classes if basicness == best_basicness]

    if len(best_ones) > 1:
        return None

    return classes[0]
