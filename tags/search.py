"""
Implements search functionality for issues and events. Arguably, putting this in tags/search.py is a bit arbitrary, but
since we have such a prominent role for tags in the actual implementation of search, this is where it ended up. And at
least it means we have all of this together in a separate file this way.
"""

import re
from django.db.models import Q, Subquery
from collections import namedtuple

from bugsink.moreiterutils import tuplewise

from .models import TagValue, IssueTag, EventTag


ParsedQuery = namedtuple("ParsedQ", ["tags", "plain_text"])


def _remove_slices(s, slices_to_remove):
    """Returns s with the slices removed."""
    items = [item for tup in slices_to_remove for item in tup]
    slices_to_preserve = tuplewise([0] + items + [None])
    return "".join(s[start:stop] for start, stop in slices_to_preserve)


def _and_join(q_objects):
    if len(q_objects) == 0:
        # we _could_ just return Q(), but I'd force the calling location to not do this
        raise ValueError("empty list of Q objects")

    result = q_objects[0]
    for q in q_objects[1:]:
        result &= q

    return result


def parse_query(q):
    # The simplest possible query-language that could have any value: key:value is recognized as such; the rest is "free
    # text"; no support for quoting of spaces.
    tags = {}

    slices_to_remove = []

    # first, match all key:value pairs with unquoted values
    for match in re.finditer(r'(\S+):([^\s"]+)', q):
        slices_to_remove.append(match.span())
        key, value = match.groups()
        tags[key] = value

    # then, match all key:"quoted value" pairs
    for match in re.finditer(r'(\S+):"([^"]+)"', q):
        slices_to_remove.append(match.span())
        key, value = match.groups()
        tags[key] = value

    slices_to_remove.sort(key=lambda tup: tup[0])  # _remove_slices expects the slices to be sorted

    plain_text_q = _remove_slices(q, slices_to_remove).strip()

    return ParsedQuery(tags, plain_text_q)


def _search(TagClz, fk_fieldname, project, obj_list, q):
    if not q:
        return obj_list

    parsed = parse_query(q)

    # The simplest possible query-language that could have any value: key:value is recognized as such; the rest is "free
    # text"; no support for quoting of spaces.
    clauses = []
    for key, value in parsed.tags.items():
        try:
            # Since we have project as a field on TagValue, we _could_ filter on project directly; with our current set
            # of indexes the below formulation is a nice way to reuse the index on TagKey (project, key) though.
            tag_value_obj = TagValue.objects.get(key__project=project, key__key=key, value=value)
        except TagValue.DoesNotExist:
            # if the tag doesn't exist, we can't have any issues with it; the below short-circuit is fine, I think (I
            # mean: we _could_ say "tag x is to blame" but that's not what one does generally in search, is it?
            return obj_list.none()

        # TODO: Extensive performance testing of various choices here is necessary; in particular the choice of Subquery
        # vs. joins; and the choice of a separate query to get TagValue v.s. doing everything in a single big query will
        # have different trade-offs _in practice_.
        clauses.append(
            Q(id__in=Subquery(TagClz.objects.filter(value=tag_value_obj).values_list(fk_fieldname, flat=True))))

    # this is really TSTTCPW (or more like a "fake it till you make it" thing); but I'd rather "have something" and then
    # have really-good-search than to have either nothing at all, or half-baked search. Note that we didn't even bother
    # to set indexes on the fields we search on (nor create a single searchable field for the whole of 'title').
    # Some notes on the current limitations and ways to improve:
    # * performance-wise: icontains queries are expensive (the "%" is on two sides, hence no index can be used); for
    #   limited data, this may be fine, but for anything over a few thousand records, this will be slow. (We might want
    #   to just do prefix-matching; or do the "both sides" thing only for small datasets).
    #
    # * performance-wise: the initial impl. only supported Issue-search; we now also allow Event-search; but there are
    #   often many more events than issues.
    #
    # * the current implementation does not work for plain text queries that span the type/value boundary; nor does it
    #   work for searching on "message" (for log messages).
    if parsed.plain_text:
        clauses.append(
            Q(Q(calculated_type__icontains=parsed.plain_text) | Q(calculated_value__icontains=parsed.plain_text)))

    # if we reach this point, there's always either a plain_text_q or some key/value pair (this is a condition for
    # _and_join)
    obj_list = obj_list.filter(_and_join(clauses))

    return obj_list


def search_issues(project, issue_list, q):
    return _search(IssueTag, "issue_id", project, issue_list, q)


def search_events(project, event_list, q):
    return _search(EventTag, "event_id", project, event_list, q)
