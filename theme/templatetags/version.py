from bugsink.version import __version__
from django import template

register = template.Library()


@register.simple_tag
def version():
    return __version__
