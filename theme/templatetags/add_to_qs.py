from copy import copy
from django import template
from django.utils.http import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def add_to_qs(context, **kwargs):
    """add kwargs to query string"""

    if 'request' not in context:
        # "should not happen", because this tag is only assumed to be used in RequestContext templates, but it's not
        # something I want to break for. Also: we have an answer that "mostly works" for that case, so let's do that.
        return urlencode(kwargs)

    query = copy(context['request'].GET.dict())
    query.update(kwargs)
    return urlencode(query)


@register.simple_tag(takes_context=True)
def current_qs(context):
    if 'request' not in context:
        # "should not happen", because this tag is only assumed to be used in RequestContext templates, but it's not
        # something I want to break for. Also: we have an answer that "mostly works" for that case, so let's do that.
        return ""

    query = copy(context['request'].GET.dict())
    if query:
        return '?' + urlencode(query)
    return ""
