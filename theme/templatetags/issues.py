from django import template
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter
def pygmentize(value):
    # first, get the actual code from the frame
    code = "\n".join(value['pre_context'] + [value['context_line']] + value['post_context'])
    return(mark_safe(highlight(code, PythonLexer(), HtmlFormatter())))


@register.filter(name='firstlineno')
def firstlineno(value):
    return value['lineno'] - len(value['pre_context'])
