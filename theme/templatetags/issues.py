from django import template
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from pygments.lexers import guess_lexer_for_filename

from django.utils.safestring import mark_safe


register = template.Library()


def _split(joined, lengths):
    result = []
    start = 0
    for length in lengths:
        result.append(joined[start:start + length])
        start += length

    assert [len(r) for r in result] == lengths
    return result


def _core_pygments(code, filename=None):
    # PythonLexer(stripnl=False) does not actually work; we work around it by inserting a space in the empty lines
    # before calling this function.
    lexer = guess_lexer_for_filename(filename, code) if filename else PythonLexer()

    result = highlight(code, lexer, HtmlFormatter(nowrap=True))

    # I can't actually get the assertion below to work stably on the level of _core_pygments(code), so it is commented
    # out. This is because at the present level we have to deal with both pygments' funnyness, and the fact that "what
    # a line is" is not properly defined. (i.e.: is the thing after the final newline a line or not, both for the input
    # and the output?). At the level of _pygmentize_lines the idea of a line is properly defined, so we only have to
    # deal with pygments' funnyness.
    # assert len(code.split("\n")) == result.count("\n"), "%s != %s" % (len(code.split("\n")), result.count("\n"))

    return result


def _pygmentize_lines(lines, filename=None):
    if lines == []:
        # special case; sending the empty string to pygments will result in one newline too many
        return []

    # newlines should by definition not be part of the code given the fact that it is presented to us as a list of
    # lines. However, we have seen cases where newlines are present in the code, e.g. in the case of the sentry_sdk's
    # integration w/ Django giving a TemplateSyntaxError (see assets/sentry-sdk-issues/django-templates.md).
    # we also add a space to the empty lines to make sure that they are not removed by the pygments formatter
    lines = [" " if line == "" else line for line in [l.replace("\n", "") for l in lines]]
    code = "\n".join(lines)
    result = _core_pygments(code, filename=filename).split('\n')[:-1]  # remove the last empty line, a result of split()
    assert len(lines) == len(result), "%s != %s" % (len(lines), len(result))
    return result


@register.filter
def pygmentize(value):
    filename = value.get('filename')

    if value.get('context_line') is None:
        # when there is no code to pygmentize we just return as-is
        return value

    code_as_list = value.get('pre_context', []) + [value['context_line']] + value.get('post_context', [])
    lengths = [len(value.get('pre_context', [])), 1, len(value.get('post_context', []))]

    lines = _pygmentize_lines(code_as_list, filename=filename)

    pre_context, context_lines, post_context = _split(lines, lengths)

    value['pre_context'] = [mark_safe(s) for s in pre_context]
    value['context_line'] = mark_safe(context_lines[0])
    value['post_context'] = [mark_safe(s) for s in post_context]

    return value


@register.filter(name='firstlineno')
def firstlineno(value):
    if value.get("lineno") is None:
        return None
    return value['lineno'] - len(value.get('pre_context', []))
