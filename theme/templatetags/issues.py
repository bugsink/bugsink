from django import template
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
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


def _core_pygments(code):
    # PythonLexer(stripnl=False) does not actually work; we work around it by inserting a space in the empty lines
    # before calling this function.
    result = highlight(code, PythonLexer(), HtmlFormatter(nowrap=True))

    # I can't actually get the assertion below to work stably on the level of _core_pygments(code), so it is commented
    # out. This is because at the present level we have to deal with both pygments' funnyness, and the fact that "what
    # a line is" is not properly defined. (i.e.: is the thing after the final newline a line or not, both for the input
    # and the output?). At the level of _pygmentize_lines the idea of a line is properly defined, so we only have to
    # deal with pygments' funnyness.
    # assert len(code.split("\n")) == result.count("\n"), "%s != %s" % (len(code.split("\n")), result.count("\n"))

    return result


def _pygmentize_lines(lines):
    if lines == []:
        # special case; sending the empty string to pygments will result in one newline too many
        return []

    # newlines should by definition not be part of the code given the fact that it is presented to us as a list of
    # lines. However, we have seen cases where newlines are present in the code, e.g. in the case of the sentry_sdk's
    # integration w/ Django giving a TemplateSyntaxError (see assets/sentry-sdk-issues/django-templates.md).
    # we also add a space to the empty lines to make sure that they are not removed by the pygments formatter
    lines = [" " if line == "" else line.replace("\n", "") for line in lines]
    code = "\n".join(lines)
    result = _core_pygments(code).split('\n')[:-1]  # remove the last empty line, which is a result of split()
    assert len(lines) == len(result), "%s != %s" % (len(lines), len(result))
    return result


@register.filter
def pygmentize(value):
    context_lines = [value['context_line']] if value['context_line'] is not None else []

    code_as_list = value['pre_context'] + context_lines + value['post_context']
    lengths = [len(value['pre_context']), len(context_lines), len(value['post_context'])]

    lines = _pygmentize_lines(code_as_list)

    pre_context, context_lines, post_context = _split(lines, lengths)

    value['pre_context'] = [mark_safe(s) for s in pre_context]
    value['context_line'] = mark_safe(context_lines[0])
    value['post_context'] = [mark_safe(s) for s in post_context]

    return value


@register.filter(name='firstlineno')
def firstlineno(value):
    return value['lineno'] - len(value['pre_context'])
