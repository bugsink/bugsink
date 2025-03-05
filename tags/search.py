"""
Implements search functionality for issues and events. Arguably, putting this in tags/search.py is a bit arbitrary, but
since we have such a prominent role for tags in the actual implementation of search, this is where it ended up. And at
least it means we have all of this together in a separate file this way.
"""

import re
from django.db.models import Q, Subquery

from bugsink.moreiterutils import tuplewise

from .models import TagValue, IssueTag, EventTag


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


def search_issues(project, issue_list, q):
    if not q:
        return issue_list

    # The simplest possible query-language that could have any value: key:value is recognized as such; the rest is "free
    # text"; no support for quoting of spaces.
    slices_to_remove = []
    clauses = []
    for match in re.finditer(r"(\S+):(\S+)", q):
        slices_to_remove.append(match.span())
        key, value = match.groups()
        try:
            tag_value_obj = TagValue.objects.get(project=project, key__key=key, value=value)
        except TagValue.DoesNotExist:
            # if the tag doesn't exist, we can't have any issues with it; the below short-circuit is fine, I think (I
            # mean: we _could_ say "tag x is to blame" but that's not what one does generally in search, is it?
            return issue_list.none()

        # TODO: Extensive performance testing of various choices here is necessary; in particular the choice of Subquery
        # vs. joins; and the choice of a separate query to get TagValue v.s. doing everything in a single big query will
        # have different trade-offs _in practice_.
        clauses.append(
            Q(id__in=Subquery(IssueTag.objects.filter(value=tag_value_obj).values_list("issue_id", flat=True))))

    # this is really TSTTCPW (or more like a "fake it till you make it" thing); but I'd rather "have something" and then
    # have really-good-search than to have either nothing at all, or half-baked search. Note that we didn't even bother
    # to set indexes on the fields we search on (nor create a single searchable field for the whole of 'title').
    plain_text_q = _remove_slices(q, slices_to_remove).strip()
    if plain_text_q:
        clauses.append(Q(Q(calculated_type__icontains=plain_text_q) | Q(calculated_value__icontains=plain_text_q)))

    # if we reach this point, there's always either a plain_text_q or some key/value pair (this is a condition for
    # _and_join)
    issue_list = issue_list.filter(_and_join(clauses))

    return issue_list


def search_events(project, event_list, q):
    if not q:
        return event_list

    # The simplest possible query-language that could have any value: key:value is recognized as such; the rest is "free
    # text"; no support for quoting of spaces.
    slices_to_remove = []
    clauses = []
    for match in re.finditer(r"(\S+):(\S+)", q):
        slices_to_remove.append(match.span())
        key, value = match.groups()
        try:
            tag_value_obj = TagValue.objects.get(project=project, key__key=key, value=value)
        except TagValue.DoesNotExist:
            # if the tag doesn't exist, we can't have any events with it; the below short-circuit is fine, I think (I
            # mean: we _could_ say "tag x is to blame" but that's not what one does generally in search, is it?
            return event_list.none()

        # TODO: Extensive performance testing of various choices here is necessary; in particular the choice of Subquery
        # vs. joins; and the choice of a separate query to get TagValue v.s. doing everything in a single big query will
        # have different trade-offs _in practice_.
        clauses.append(
            Q(id__in=Subquery(EventTag.objects.filter(value=tag_value_obj).values_list("event_id", flat=True))))

    # this is really TSTTCPW (or more like a "fake it till you make it" thing); but I'd rather "have something" and then
    # have really-good-search than to have either nothing at all, or half-baked search. Note that we didn't even bother
    # to set indexes on the fields we search on (nor create a single searchable field for the whole of 'title').
    plain_text_q = _remove_slices(q, slices_to_remove).strip()
    if plain_text_q:
        clauses.append(Q(Q(calculated_type__icontains=plain_text_q) | Q(calculated_value__icontains=plain_text_q)))

    # if we reach this point, there's always either a plain_text_q or some key/value pair (this is a condition for
    # _and_join)
    event_list = event_list.filter(_and_join(clauses))

    return event_list
