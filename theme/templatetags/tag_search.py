from urllib.parse import quote

from django import template

register = template.Library()


def _quoted(value):
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def _tag_clause(key, value):
    key = str(key)
    if any(char.isspace() or char in ':"\\' for char in key):
        key = _quoted(key)
    return "%s:%s" % (key, _quoted(value))


@register.simple_tag
def tag_drilldown(current_q, key, value):
    # URL-encoded `?q=` value that appends `key:"value"` to the active query, so clicking a tag narrows the current
    # search (drilldown) instead of replacing it. parse_query dedupes tags by key, so re-clicking a tag is idempotent.
    clause = _tag_clause(key, value)
    return quote(("%s %s" % (current_q, clause)).strip() if current_q else clause)
