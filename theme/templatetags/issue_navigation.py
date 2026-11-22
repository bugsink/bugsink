from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag
def global_issue_list_url(url):
    paths = [reverse(f"global_issue_list_{state}") for state in ("open", "unresolved", "muted", "resolved", "all")]
    if not url or url.partition("?")[0] not in paths:
        return ""
    return url
