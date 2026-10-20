"""
Implements search functionality for issues and events. Arguably, putting this in tags/search.py is a bit arbitrary, but
since we have such a prominent role for tags in the actual implementation of search, this is where it ended up. And at
least it means we have all of this together in a separate file this way.
"""

import re
from collections import namedtuple
from datetime import datetime, time, timedelta

from django.db.models import Q, Subquery, Count
from django.utils import timezone
from django.utils.dateparse import parse_date

from bugsink.moreiterutils import tuplewise
from events.models import Event

from .models import TagValue, IssueTag, EventTag, _or_join


ParsedQuery = namedtuple("ParsedQ", ["tags", "plain_text"])


class SearchError(ValueError):
    """Raised for a query that can't be parsed (e.g. a bad date or an unknown level). Surfaced to the user."""


# Whitelist of Issue fields that can be filtered directly (as opposed to tags). The whitelist is the trust boundary:
# only these names ever reach the ORM. "ops" is the set of operators the field accepts ("" means plain equality).
ISSUE_SEARCH_FIELDS = {
    "first_seen": {"field": "first_seen", "type": "datetime", "ops": {"", ">", ">=", "<", "<="}},
    "last_seen": {"field": "last_seen", "type": "datetime", "ops": {"", ">", ">=", "<", "<="}},
    "events": {"field": "digested_event_count", "type": "int", "ops": {"", ">", ">=", "<", "<="}},
    "is_muted": {"field": "is_muted", "type": "bool", "ops": {""}},
    "is_resolved": {"field": "is_resolved", "type": "bool", "ops": {""}},
}

_LOOKUP = {"": "exact", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
_OPERATORS = (">=", "<=", ">", "<")  # longest-first, so ">=" is matched before ">"
_REL_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
_REL_RE = re.compile(r"(?:now)?\s*([+-]\d+)([smhdw])", re.IGNORECASE)
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


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


def _split_on_spaces_respecting_quotes(q):
    terms = []
    start = None
    in_quotes = False
    i = 0

    while i < len(q):
        if start is None:
            if q[i].isspace():
                i += 1
                continue
            start = i

        if q[i] == "\\" and i + 1 < len(q) and q[i + 1] in ['"', "\\"]:
            i += 2
            continue

        if q[i] == '"':
            in_quotes = not in_quotes
        elif q[i].isspace() and not in_quotes:
            terms.append((start, i, True))
            start = None

        i += 1

    if start is not None:
        terms.append((start, len(q), not in_quotes))

    return terms


def _parse_tag_token(term):
    in_quotes = False
    i = 0

    while i < len(term):
        if term[i] == "\\" and i + 1 < len(term) and term[i + 1] in ['"', "\\"]:
            i += 2
            continue

        if term[i] == '"':
            in_quotes = not in_quotes
        elif term[i] == ":" and not in_quotes:
            if i == 0 or i == len(term) - 1:
                return None
            return _unquote(term[:i]), _unquote(term[i + 1:])

        i += 1

    return None


def _unquote(value):
    result = []
    i = 0

    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] in ['"', "\\"]:
            result.append(value[i + 1])
            i += 2
        elif value[i] == '"':
            i += 1
        else:
            result.append(value[i])
            i += 1

    return "".join(result)


def parse_query(q):
    tags = {}
    slices_to_remove = []

    # First split the query on spaces outside quoted strings.
    for start, stop, quotes_closed in _split_on_spaces_respecting_quotes(q):
        if not quotes_closed:
            continue

        # Then split each complete token on its first unquoted colon.
        tag = _parse_tag_token(q[start:stop])
        if tag is None:
            continue

        key, value = tag
        if not key:
            continue

        tags[key] = value
        slices_to_remove.append((start, stop))

    plain_text_q = _remove_slices(q, slices_to_remove).strip()

    return ParsedQuery(tags, plain_text_q)


def _split_key_op_value(token):
    """Splits a single token into (key, operator, value, negated), or None if it's not a key:value token."""
    negated = token.startswith("!")
    if negated:
        token = token[1:]

    in_quotes = False
    i = 0
    colon = -1
    while i < len(token):
        if token[i] == "\\" and i + 1 < len(token) and token[i + 1] in ['"', "\\"]:
            i += 2
            continue
        if token[i] == '"':
            in_quotes = not in_quotes
        elif token[i] == ":" and not in_quotes:
            colon = i
            break
        i += 1

    if colon <= 0 or colon == len(token) - 1:
        return None

    key = _unquote(token[:colon])
    rest = token[colon + 1:]

    op = ""
    for cand in _OPERATORS:
        if rest.startswith(cand):
            op, rest = cand, rest[len(cand):]
            break

    value = _unquote(rest)

    # be forgiving about a quoted operator, e.g. first_seen:">2026-10-11"
    if not op:
        for cand in _OPERATORS:
            if value.startswith(cand):
                op, value = cand, value[len(cand):].strip()
                break

    if not key or not value:
        return None

    return key, op, value, negated


def _parse_temporal(value, key):
    """Parses an absolute date (YYYY-MM-DD) or a relative value (-7d, now-1h). Returns ('date', date|'instant', dt)."""
    v = value.strip()
    if v.lower() == "now":
        return "instant", timezone.now()

    m = _REL_RE.fullmatch(v)
    if m:
        amount = int(m.group(1))
        return "instant", timezone.now() + timedelta(**{_REL_UNITS[m.group(2).lower()]: amount})

    d = parse_date(v)
    if d is not None:
        return "date", d

    raise SearchError(f"'{key}': '{value}' is not a date (use YYYY-MM-DD or a relative value like -7d)")


def _datetime_q(field, op, value, key):
    kind, when = _parse_temporal(value, key)

    if kind == "instant":
        if not op:
            raise SearchError(f"'{key}': a relative time needs an operator, e.g. {key}:>-7d")
        return Q(**{f"{field}__{_LOOKUP[op]}": when})

    # A bare date on a datetime field expands to a [start, next-day) range using plain comparisons (no __date lookup).
    # Day boundaries are taken in the active timezone.
    start = timezone.make_aware(datetime.combine(when, time.min))
    end = start + timedelta(days=1)
    return {
        "": Q(**{f"{field}__gte": start, f"{field}__lt": end}),
        ">": Q(**{f"{field}__gte": end}),
        ">=": Q(**{f"{field}__gte": start}),
        "<": Q(**{f"{field}__lt": start}),
        "<=": Q(**{f"{field}__lt": end}),
    }[op]


def _build_field_q(key, spec, op, value):
    if op and op not in spec["ops"]:
        raise SearchError(f"'{key}' does not support the '{op}' operator")

    ftype = spec["type"]
    field = spec["field"]

    if ftype == "datetime":
        return _datetime_q(field, op, value, key)

    if ftype == "int":
        try:
            n = int(value)
        except ValueError:
            raise SearchError(f"'{key}': '{value}' is not a whole number")
        return Q(**{f"{field}__{_LOOKUP[op]}": n})

    if ftype == "bool":
        v = value.lower()
        if v in _TRUE:
            return Q(**{field: True})
        if v in _FALSE:
            return Q(**{field: False})
        raise SearchError(f"'{key}': '{value}' is not true/false")

    # enum
    v = value.lower()
    if v not in spec["choices"]:
        raise SearchError(f"'{key}': '{value}' is not one of {', '.join(sorted(spec['choices']))}")
    return Q(**{field: v})


def extract_field_predicates(q, fields):
    """Pulls whitelisted `field:value` tokens out of q, returning (list of Q, q-without-those-tokens)."""
    clauses = []
    slices_to_remove = []

    for start, stop, quotes_closed in _split_on_spaces_respecting_quotes(q):
        if not quotes_closed:
            continue

        split = _split_key_op_value(q[start:stop])
        if split is None:
            continue

        key, op, value, negated = split
        if key not in fields:
            continue  # not a field; leave it for tag / plain-text handling

        clause = _build_field_q(key, fields[key], op, value)
        clauses.append(~clause if negated else clause)
        slices_to_remove.append((start, stop))

    return clauses, _remove_slices(q, slices_to_remove)


def _search(m2m_qs, fk_fieldname, project, obj_list, q, fields=None):
    if not q:
        return obj_list

    field_clauses = []
    if fields:
        field_clauses, q = extract_field_predicates(q, fields)

    parsed = parse_query(q)

    clauses = list(field_clauses)
    for key, value in parsed.tags.items():
        try:
            # Since we have project as a field on TagValue, we _could_ filter on project directly; with our current set
            # of indexes the below formulation is a nice way to reuse the index on TagKey (project, key) though.
            tag_value_obj = TagValue.objects.get(key__project=project, key__key=key, value=value)
        except TagValue.DoesNotExist:
            # if the tag doesn't exist, we can't have any issues with it; the below short-circuit is fine, I think (I
            # mean: we _could_ say "tag x is to blame" but that's not what one does generally in search, is it?
            return obj_list.none()

        clauses.append(
            Q(id__in=Subquery(m2m_qs.filter(value=tag_value_obj).values_list(fk_fieldname, flat=True))))

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

    if not clauses:
        # e.g. the query was only whitespace, or only field tokens that stripped away to nothing
        return obj_list

    return obj_list.filter(_and_join(clauses))


def search_issues(project, issue_list, q):
    return _search(IssueTag.objects.all(), "issue_id", project, issue_list, q, fields=ISSUE_SEARCH_FIELDS)


def search_events(project, issue, q):
    return _search(EventTag.objects.filter(issue=issue), "event_id", project, Event.objects.filter(issue=issue), q)


def search_event_tags(project, issue, parsed):
    if parsed.plain_text or not parsed.tags:
        raise ValueError("Only works for at least one tag and no plain text")

    clauses = []
    for key, value in parsed.tags.items():
        try:
            # Since we have project as a field on TagValue, we _could_ filter on project directly; with our current set
            # of indexes the below formulation is a nice way to reuse the index on TagKey (project, key) though.
            tag_value_obj = TagValue.objects.get(key__project=project, key__key=key, value=value)
        except TagValue.DoesNotExist:
            # if the tag doesn't exist, we can't have any issues with it; the below short-circuit is fine, I think (I
            # mean: we _could_ say "tag x is to blame" but that's not what one does generally in search, is it?
            return EventTag.objects.none()

        clauses.append(Q(issue=issue, value=tag_value_obj))

    if len(clauses) == 1:
        return EventTag.objects.filter(clauses[0])

    # We have multiple clauses; we need to find the events that have all of these tags; we can't just do a filter() with
    # and _and_join of the clauses, because ANDing 2 disjoint sets of tags will never match anything. So we need to do a
    # count of the number of events that have each of the tags, and then filter on the ones that have all of them.
    # Note that grouping-by/counting on the digest_order (rather than just event_id) works because the digest_order is
    # unique per event (in the context of a single issue); its use allows for a covering index on the OR-ed parts.
    # Note that pulling the match on issue out of the OR-ed parts to a single AND was tried, but found to be 2x slower.
    return EventTag.objects.filter(
        _or_join(clauses)).values("digest_order").annotate(count=Count("digest_order")).filter(count=len(clauses))


def search_events_optimized(project, issue, q):
    """
    Search events or event tags (which will have digest_order efficiently), based on what you can do given "q".
    """

    if not q:
        return Event.objects.filter(issue=issue)

    parsed = parse_query(q)

    if parsed.plain_text or not parsed.tags:
        # if-clause is a bit redundant given the `not q` guard above, but this fully covers the cases search_event_tags
        # can't handle;
        # in this case we just fall back to "whatever we did pre-optimization"; in other words, you're now entering the
        # "not so optimized" path. The reason is simply: we had to stop somewhere. One thing we don't try to do in
        # particular is use the result of `search_event_tags` as an inner query to construct Events (whether that's even
        # faster wasn't checked)
        return search_events(project, issue, q)

    return search_event_tags(project, issue, parsed)
