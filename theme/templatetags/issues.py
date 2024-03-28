from django import template
register = template.Library()


@register.filter(name='firstlineno')
def firstlineno(value):
    return value['lineno'] - len(value['pre_context'])
