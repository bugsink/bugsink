from django import template
import hashlib

register = template.Library()


@register.filter
def gravatar_sha(value):
    return hashlib.sha256(value.email.lower().strip().encode("utf-8")).hexdigest()


@register.filter
def best_displayname(value):
    return value.get_full_name() or value.username
