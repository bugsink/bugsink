from urllib.parse import quote

from django import template

register = template.Library()


def _tag_clause(key, value):
    # Build a Bugsink issue-search token `key:"value"`. The value is always quoted and its `"` and `\` escaped,
    # because the search parser (tags/search.py) splits the query on *unquoted* spaces before the first *unquoted*
    # colon -- so an unquoted value with a space would be truncated and a `"` would drop the filter.
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '%s:"%s"' % (key, escaped)


@register.simple_tag
def tag_drilldown(current_q, key, value):
    # URL-encoded `?q=` value that appends `key:"value"` to the active query, so clicking a tag narrows the current
    # search (drilldown) instead of replacing it. parse_query dedupes tags by key, so re-clicking a tag is idempotent.
    clause = _tag_clause(key, value)
    return quote(("%s %s" % (current_q, clause)).strip() if current_q else clause)
