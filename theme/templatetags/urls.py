from django import template
from bugsink.app_settings import get_path_prefix

register = template.Library()


@register.filter
def with_prefix(url):
    """Add the path prefix to a URL for subpath hosting support."""
    if not url:
        return url
        
    prefix = get_path_prefix()
    if not prefix:
        return url
        
    # Handle absolute URLs that start with /
    if url.startswith('/'):
        return prefix + url
    
    return url


@register.simple_tag
def prefixed_url(url):
    """Template tag version of the with_prefix filter."""
    return with_prefix(url)