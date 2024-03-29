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


def noempty(lines):
    # if the line is empty, replace it with a space; this is needed to avoid pygments dropping empty lines (I've
    # obvserved this for leading empty lines, but the problem might be more general)
    # https://github.com/pygments/pygments/issues/2673
    return [" " if not line else line for line in lines]


@register.filter
def pygmentize(value):
    # first, get the actual code from the frame
    lengths = [len(value['pre_context']), 1, len(value['post_context'])]

    code = "\n".join(noempty(value['pre_context']) + [value['context_line']] + noempty(value['post_context']))
    pygments_result = highlight(code, PythonLexer(), HtmlFormatter(nowrap=True))
    lines = pygments_result.split('\n')[:-1]  # remove the last empty line, which is a result of split()

    assert len(lines) == sum(lengths), "%d != %d" % (len(lines), sum(lengths))

    pre_context, context_lines, post_context = _split(lines, lengths)

    value['pre_context'] = [mark_safe(s) for s in pre_context]
    value['context_line'] = mark_safe(context_lines[0])
    value['post_context'] = [mark_safe(s) for s in post_context]

    return value


@register.filter(name='firstlineno')
def firstlineno(value):
    return value['lineno'] - len(value['pre_context'])
