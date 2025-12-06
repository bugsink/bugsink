from datetime import datetime
import re
from django import template
from pygments import highlight
from pygments.formatters import HtmlFormatter

from django.utils.html import escape
from django.utils.safestring import SafeData, mark_safe
from django.template.defaultfilters import date

from compat.timestamp import parse_timestamp

from sentry_sdk_extensions import capture_stacktrace
from bugsink.utils import assert_
from bugsink.pygments_extensions import guess_lexer_for_filename, lexer_for_platform

register = template.Library()


def _split(joined, lengths):
    result = []
    start = 0
    for length in lengths:
        result.append(joined[start:start + length])
        start += length

    assert_([len(r) for r in result] == lengths)
    return result


def _core_pygments(code, filename=None, platform=None):
    # PythonLexer(stripnl=False) does not actually work; we work around it by inserting a space in the empty lines
    # before calling this function.

    # note: we don't use pygments' `guess_lexer(text)` function because it is basically useless, especially when only
    # snippets of code are available. Check the implementation of `analyse_text` in the various lexers to see why (e.g.
    # perl and python are particularly bad). Better just use the platform (even though that's broader than a single
    # frame, since it applies to the whole event). A happy side effect of using `lexer_for_platform` is that it's fast.
    # Note: this only matters in the presumably rare case that the filename is not available (or useful) but the source
    # code is.

    if filename:
        lexer = guess_lexer_for_filename(filename, platform, code=code)
        if lexer is None:
            lexer = lexer_for_platform(platform)
    else:
        lexer = lexer_for_platform(platform)

    result = highlight(code, lexer, HtmlFormatter(nowrap=True))

    # I can't actually get the assertion below to work stably on the level of _core_pygments(code), so it is commented
    # out. This is because at the present level we have to deal with both pygments' funnyness, and the fact that "what
    # a line is" is not properly defined. (i.e.: is the thing after the final newline a line or not, both for the input
    # and the output?). At the level of _pygmentize_lines the idea of a line is properly defined, so we only have to
    # deal with pygments' funnyness.
    # assert_(len(code.split("\n")) == result.count("\n"), "%s != %s" % (len(code.split("\n")), result.count("\n")))

    return result


def _pygmentize_lines(lines, filename=None, platform=None):
    if lines == []:
        # special case; sending the empty string to pygments will result in one newline too many
        return []

    # newlines should by definition not be part of the code given the fact that it is presented to us as a list of
    # lines. However, we have seen cases where newlines are present in the code, e.g. in the case of the sentry_sdk's
    # integration w/ Django giving a TemplateSyntaxError (see assets/sentry-sdk-issues/django-templates.md).
    # we also add a space to the empty lines to make sure that they are not removed by the pygments formatter
    lines = [" " if line == "" else line for line in [l.replace("\n", "") for l in lines]]
    code = "\n".join(lines)

    # [:-1] to remove the last empty line, a result of split()
    result = _core_pygments(code, filename=filename, platform=platform).split('\n')[:-1]
    if len(lines) != len(result):
        capture_stacktrace("Pygments line count mismatch, falling back to unformatted code")
        result = lines

    return result


def d_get_l(d, key):
    # returns an empty list for both missing keys and present-but-None keys
    result = d.get(key)
    if result is None:
        return []
    return result


@register.filter
def pygmentize(value, platform):
    filename = value.get('filename')

    if value.get('context_line') is None:
        # when there is no code to pygmentize we just return as-is
        return value

    code_as_list = d_get_l(value, 'pre_context') + [value['context_line']] + d_get_l(value, 'post_context')

    # as per event.schema.json, it's possible that the list of lines contains None values (via pre_context and
    # post_context), although it's not clear what that would mean. We just replace them with empty strings.
    code_as_list = ["" if line is None else line for line in code_as_list]

    lengths = [len(d_get_l(value, 'pre_context')), 1, len(d_get_l(value, 'post_context'))]

    lines = _pygmentize_lines(code_as_list, filename=filename, platform=platform)

    pre_context, context_lines, post_context = _split(lines, lengths)

    # no_bandit_expl: see tests.TestPygmentizeEscape
    value['pre_context'] = [mark_safe(s) for s in pre_context]  # nosec B703, B308
    value['context_line'] = mark_safe(context_lines[0])  # nosec B703, B308
    value['post_context'] = [mark_safe(s) for s in post_context]  # nosec B703, B308

    return value


@register.filter(name='firstlineno')
def firstlineno(value):
    if value.get("lineno") is None:
        return None
    return value['lineno'] - len(d_get_l(value, 'pre_context'))


SHA_RE = re.compile(r"[0-9a-f]+")


@register.filter(name='issha')
def issha(value):
    """does this look like a sha?"""
    if len(value) not in [12, 16, 20, 32, 40, 64]:
        return False

    if not SHA_RE.fullmatch(value):
        return False

    return True


@register.filter(name='shortsha')
def shortsha(value):
    """_if_ this value looks like a version hash, make it short"""
    if not issha(value):
        return value

    return value[:12]


def safe_join(sep, items, strict=False):
    """join() that takes safe strings into account; strict=True means: I expect all inputs to be safe"""

    text = sep.join(items)
    if isinstance(sep, SafeData) and all(isinstance(i, SafeData) for i in items):
        # no_bandit_expl: as per the check right above
        return mark_safe(text)  # nosec B703, B308
    if strict:
        raise ValueError("Cannot join non-safe in strict mode")
    return text


@register.filter()
def format_var(value):
    """Formats a variable for display in the template; deals with 'marked as incomplete'."""
    # this is a non-recursive version of the function below, which is faster and allows for arbitrary nesting.
    # implementation: `todo` is a generator object that yields [1] parts of the result, and [2] instructions to recurse,
    # which we interpret manually using a python-list "stack"

    def storevalue(v):
        # sentinel function to store the value for later retrieval; because JSON contains no callables this allows us
        # to distinguish between `None` meaning no recurse and `None`, a value that needs to be displayed.
        def get():
            return v
        return get

    def gen_base(obj):
        yield escape(str(obj)), None

    def bracket_wrap(gen, b_open, sep, b_close):
        yield b_open, None
        fst = True
        for part, recurse in gen:
            if not fst:
                yield sep, None
            yield part, recurse
            fst = False
        yield b_close, None

    def gen_list(lst):
        for value in lst:
            yield escape(""), storevalue(value)

        if hasattr(lst, "incomplete"):
            # no_bandit_expl: constant string w/ substitution of an int (asserted)
            assert_(isinstance(lst.incomplete, int))
            yield mark_safe(f"<i>&lt;{lst.incomplete} items trimmed…&gt;</i>"), None  # nosec B703, B308

    def gen_dict(d):
        for (k, v) in d.items():
            yield escape(repr(k)) + escape(": "), storevalue(v)

        if hasattr(d, "incomplete"):
            # no_bandit_expl: constant string w/ substitution of an int (asserted)
            assert_(isinstance(d.incomplete, int))
            yield mark_safe(f"<i>&lt;{d.incomplete} items trimmed…&gt;</i>"), None  # nosec B703, B308

    def gen_switch(obj):
        if isinstance(obj, list):
            return bracket_wrap(gen_list(obj), escape("["), escape(", "), escape("]"))
        if isinstance(obj, dict):
            return bracket_wrap(gen_dict(obj), escape("{"), escape(", "), escape("}"))
        return gen_base(obj)

    result = []
    stack = []
    todo = gen_switch(value)
    done = False

    while not done:
        try:
            part, recurse = next(todo)
            result.append(part)
        except StopIteration:
            recurse = None
            if stack:
                todo = stack.pop()
            else:
                done = True

        if callable(recurse):
            stack.append(todo)
            todo = gen_switch(recurse())

    return safe_join(escape(""), result, strict=True)


# recursive equivalent:
# @register.filter()
# def format_var(value):
#     """Formats a variable for display in the template; deals with 'marked as incomplete'.
#     """
#     if isinstance(value, dict):
#         parts = [(escape(repr(k)) + escape(": ") + format_var(v)) for (k, v) in value.items()]
#         if hasattr(value, "incomplete"):
#             parts.append(mark_safe(f"<i>&lt;{value.incomplete} items trimmed…&gt;</i>"))
#         return escape("{") + safe_join(escape(", "), parts, strict=True) + escape("}")
#
#     if isinstance(value, list):
#         parts = [format_var(v) for v in value]
#         if hasattr(value, "incomplete"):
#             parts.append(mark_safe(f"<i>&lt;{value.incomplete} items trimmed…&gt;</i>"))
#         return escape("[") + safe_join(escape(", "), parts, strict=True) + escape("]")
#
#     return escape(value)


@register.filter()
def incomplete(value):
    # needed to disinguish between 'has an incomplete' attr (set by us) and 'contains an incomplete key' (event-data)
    return hasattr(value, "incomplete")


def _date_with_milis_html(timestamp):
    # no_bandit_expl: constant string w/ substitution of dates/milis (escaped even), see also TimestampWithMillisTagTest
    return (
        mark_safe('<span class="whitespace-nowrap">') +  # nosec
        escape(date(timestamp, "j M G:i:s")) + mark_safe(".") +  # nosec
        mark_safe('<span class="text-xs">') + escape(date(timestamp, "u")[:3]) +  # nosec
        mark_safe('</span></span>'))  # nosec


@register.filter
def timestamp_with_millis(value):
    """
    Timestamp formatting with milliseconds; robust for datetime.datetime, as well as the strings/floats/ints that may
    show up in the event data.
    """
    if isinstance(value, datetime):
        dt = value

    else:
        try:
            dt = parse_timestamp(value)
        except Exception:
            return value

    if dt is None:
        return value

    return _date_with_milis_html(dt)
