from django import template

register = template.Library()


@register.filter
def tag_query(key, value):
    # Build a Bugsink issue-search token `key:"value"` for a tag filter link. The value is always quoted and its `"`
    # and `\` escaped, because the search parser (tags/search.py) splits the query on *unquoted* spaces before the
    # first *unquoted* colon -- so an unquoted value with a space would be truncated and a `"` would drop the filter.
    # The caller is expected to run the result through |urlencode.
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '%s:"%s"' % (key, escaped)
