from enum import Enum
import hashlib
import json
import logging

import fastjsonschema
import jsonschema

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F, Sum

from bugsink.app_settings import get_settings
from bugsink.transaction import delay_on_commit
from events.models import Event
from issues.grouping_mechanisms import (
    GROUPING_TRANSITION_PERIOD, BUGSINK_GROUPING_V1, MECHANISM_INDEPENDENT_GROUPING)
from issues.models import Issue, IssueStateManager, Grouping
from issues.utils import get_key_with_mechanism_for_data
from projects.models import Project

from .event_counter import check_for_thresholds, count_for_thresholds, filter_for_periods, state_for_threshold


class GroupingPath(Enum):
    FOUND = "found"
    NEW = "new"
    ATTACH = "attach"


QUOTA_THRESHOLDS = {
    "Installation": [
        ("minute", 5, "MAX_EVENTS_PER_5_MINUTES"),
        ("hour", 1, "MAX_EVENTS_PER_HOUR",),
        ("month", 1, "MAX_EVENTS_PER_MONTH"),
    ],
    "Project": [
        ("minute", 5, "MAX_EVENTS_PER_PROJECT_PER_5_MINUTES"),
        ("hour", 1, "MAX_EVENTS_PER_PROJECT_PER_HOUR",),
        ("month", 1, "MAX_EVENTS_PER_PROJECT_PER_MONTH"),
    ],
}

logger = logging.getLogger("bugsink.ingest")


def update_issue_counts(per_issue):
    # we minimize the number of queries by grouping them by count; in the worst case we'll need 32 queries for 500
    # event evictions (because 1 + 2 + ... + 31 + 32 > 500)
    by_count = {}
    for issue_id, count in per_issue.items():
        by_count.setdefault(count, []).append(issue_id)

    for count, issue_ids in by_count.items():
        Issue.objects.filter(id__in=issue_ids).update(stored_event_count=F("stored_event_count") - count)


def get_grouping_key_hash(grouping_key):
    return hashlib.sha256(grouping_key.encode()).hexdigest()


def get_existing_grouping(project_id, key_with_mechanism):
    # helper to get the existing grouping for a given key/mechanism pair, if it exists.
    return Grouping.objects.filter(
        project_id=project_id,
        grouping_key=key_with_mechanism.key,
        grouping_key_hash=get_grouping_key_hash(key_with_mechanism.key),
        grouping_mechanism=key_with_mechanism.mechanism,
    ).first()


def get_legacy_grouping_for_mechanism_independent_key(project_id, key_with_mechanism):
    return Grouping.objects.filter(
        project_id=project_id,
        grouping_key=key_with_mechanism.key,
        grouping_key_hash=get_grouping_key_hash(key_with_mechanism.key),
        grouping_mechanism=BUGSINK_GROUPING_V1,
    ).first()


def create_grouping(project_id, key_with_mechanism, issue):
    return Grouping.objects.create(
        project_id=project_id,
        grouping_key=key_with_mechanism.key,
        grouping_key_hash=get_grouping_key_hash(key_with_mechanism.key),
        grouping_mechanism=key_with_mechanism.mechanism,
        issue=issue,
    )


def grouping_transition_is_active(project, digested_at):
    if project.previous_grouping_mechanism is None or project.grouping_mechanism_upgraded_at is None:
        return False

    return digested_at <= project.grouping_mechanism_upgraded_at + GROUPING_TRANSITION_PERIOD


def get_grouping_path_for_event(project, event_data, digested_at):
    # First try the project's current mechanism.
    current_key_with_mechanism = get_key_with_mechanism_for_data(
        event_data, grouping_mechanism=project.grouping_mechanism)
    if (current_grouping := get_existing_grouping(project.id, current_key_with_mechanism)) is not None:
        return GroupingPath.FOUND, (current_grouping,)

    if current_key_with_mechanism.mechanism == MECHANISM_INDEPENDENT_GROUPING:
        # special case for imprecisely migrated data, i.e. this is "another piece of legacy-handling code in the digest
        # path" as mentioned in the migration file: because we may not have correctly identified all mechanismless
        # groupings we allow matching with v1 here.
        #
        # this is really the 10%/1% correctness for avoiding some unnecesary splits so it can be removed "quite soon",
        # e.g. in October 2026.
        legacy_grouping = get_legacy_grouping_for_mechanism_independent_key(project.id, current_key_with_mechanism)
        if legacy_grouping is not None:
            return GroupingPath.ATTACH, (current_key_with_mechanism, legacy_grouping)
        return GroupingPath.NEW, (current_key_with_mechanism,)

    # Current mechanism not found, no special-case, and we're not in the transition window: this is a new grouping.
    if not grouping_transition_is_active(project, digested_at):
        return GroupingPath.NEW, (current_key_with_mechanism,)

    # During the transition window, retry the previous mechanism.
    previous_key_with_mechanism = get_key_with_mechanism_for_data(
        event_data, grouping_mechanism=project.previous_grouping_mechanism)
    if (previous_grouping := get_existing_grouping(project.id, previous_key_with_mechanism)) is not None:
        return GroupingPath.ATTACH, (current_key_with_mechanism, previous_grouping)

    # No grouping found for either mechanism, so this is a new grouping.
    return GroupingPath.NEW, (current_key_with_mechanism,)


def check_for_thresholds_on_installation(qs, now, thresholds, add_for_current=0):
    # project_digest_order is only monotonic per project, so installation-wide counting sums project-local results
    # rather than trying to pretend there is a single installation-wide order.
    project_ids = list(qs.order_by().values_list("project_id", flat=True).distinct())
    total_events_in_periods = [add_for_current] * len(thresholds)

    for project_id in project_ids:
        project_counts = count_for_thresholds(qs.filter(project_id=project_id), now, thresholds)
        for i, (project_total_events_in_period, _) in enumerate(project_counts):
            total_events_in_periods[i] += project_total_events_in_period

    states = []
    for i, threshold in enumerate(thresholds):
        period_name, nr_of_periods, _ = threshold
        qs_for_period = filter_for_periods(qs, period_name, nr_of_periods, now)
        states.append(state_for_threshold(qs_for_period, now, total_events_in_periods[i], threshold))

    return states


def validate_event_data(data, validation_setting):
    # Rough timings for a 50k event: valid ~1ms, invalid ~100ms.
    # The invalid-data cost is almost entirely in the jsonschema fallback

    def get_schema():
        schema_filename = settings.BASE_DIR / 'api/event.schema.altered.json'
        with open(schema_filename, 'r') as f:
            return json.loads(f.read())

    def validate():
        # helper function that wraps the idea of "validate quickly, but fail meaningfully"
        try:
            validate_event_data._event_validator(data_to_validate)
        except fastjsonschema.exceptions.JsonSchemaValueException as fastjsonschema_e:
            # fastjsonchema's exceptions provide almost no information (in the case of many anyOfs), so we just fall
            # back to jsonschema for that. Slow (and double cost), but failing is the rare case, so we don't care.
            # https://github.com/horejsek/python-fastjsonschema/issues/72 and 37 for some context
            try:
                jsonschema.validate(data_to_validate, get_schema())
            except jsonschema.ValidationError as inner_e:
                best = jsonschema.exceptions.best_match([inner_e])
                # we raise 'from best' here; this does lose some information w.r.t. 'from inner_e', but it's my
                # belief that it's not useful info we're losing. similarly, but more so for 'fastjsonschema_e'.
                raise ValidationError(best.json_path + ": " + best.message, code="invalid_event_data") from best

            # in the (presumably not-happening) case that our fallback validation succeeds, fail w/o useful message
            raise ValidationError(fastjsonschema_e.message, code="invalid_event_data") from fastjsonschema_e

    # the schema is loaded once and cached on the function (it's in the 1-2ms range, but my measurements varied a lot
    # so I'm not sure and I'd rather cache (and not always load) a file in the 2.5MB range than to just assume it's
    # fast)
    if not hasattr(validate_event_data, "_event_validator"):
        from bugsink.event_schema import validate as validate_schema
        validate_event_data._event_validator = validate_schema

    # known fields that are not part of the schema (and that we don't want to validate)
    data_to_validate = {k: v for k, v in data.items() if k != "_meta"}

    if validation_setting == "strict":
        validate()

    else:  # i.e. "warn" - we never reach this function for "none"
        try:
            validate()
        except ValidationError as e:
            logger.warning("event data validation failed: %s", e)


def handle_zero_retention(project):
    # With zero retention the caller must return (don't digest) before doing any work. Otherwise we'd retain an
    # event despite the zero limit, because we do evict-before-add which doesn't work for the case of 0.
    if project.get_retention_max_event_count() != 0:
        return False

    if project.stored_event_count > 0:
        from events.tasks import delete_by_age_until_under_retention_max
        # Since we don't evict in this branch, we just have the simplest hard-coded eviction (delete below max):
        delay_on_commit(delete_by_age_until_under_retention_max, project.id)
    return True


def count_installation_periods_and_act_on_it(installation, now):
    # Copy/pasted from count_project_periods_and_act_on_it and adapted. Explaining comments from over there were not
    # kept; the comments below are specific to the adapations.
    thresholds = [(p, n, get_settings()[key]) for (p, n, key) in QUOTA_THRESHOLDS["Installation"]]
    min_threshold = min([gte_threshold for (_, _, gte_threshold) in thresholds])

    if is_quota_still_exceeded(installation, now):
        return False

    # We don't do per-event-digest bookkeeping on the installation because doing so would tie us in further into
    # "global locking"; the assumption is that a group by over (a few) projects is still quite cheap. The per-exceed
    # bookkeeping _is_ done on the installation level (moments of exceeding are quite rare; cost is amortized).
    # +1 because about-to-add and the installation-wide call precedes the per-project bookkeeping.
    digested_event_count = (Project.objects.aggregate(total=Sum("digested_event_count"))["total"] or 0) + 1

    if ((digested_event_count >= installation.next_quota_check) or
            (installation.next_quota_check - digested_event_count > min_threshold)):

        states = check_for_thresholds_on_installation(Event.objects.all(), now, thresholds, 1)

        until, threshold_info = max(
            [(below_from, ti) for (is_exceeded, below_from, _, ti) in states if is_exceeded],
            default=(None, None))

        check_again_after = max(1, min([check_after for (_, _, check_after, _) in states], default=1))

        installation.quota_exceeded_until = until  # note: never reset to None, but the `now <` will still just work
        installation.quota_exceeded_reason = json.dumps(threshold_info)
        installation.next_quota_check = digested_event_count + check_again_after
        installation.save()  # conditional in the if-statement because no per-digest bookkeeping on the installation

    return True


def is_quota_still_exceeded(obj, now):
    if obj.quota_exceeded_until is None or now >= obj.quota_exceeded_until:
        return False

    # check if the setting has not been made more lax since the quota was tripped (an alternative would be: always
    # reset these on snappea/server start)
    period_name, nr_of_periods, gte_threshold = json.loads(obj.quota_exceeded_reason)
    relevant_setting = [
        k for (p, n, k) in QUOTA_THRESHOLDS[type(obj).__name__]
        if p == period_name and n == nr_of_periods
    ][0]
    current_gte_threshold = get_settings()[relevant_setting]
    if current_gte_threshold > gte_threshold:
        return False

    return True


def count_project_periods_and_act_on_it(project, now):
    # returns: True if any further processing should be done.
    thresholds = [(p, n, get_settings()[key]) for (p, n, key) in QUOTA_THRESHOLDS["Project"]]
    min_threshold = min([gte_threshold for (_, _, gte_threshold) in thresholds])

    if is_quota_still_exceeded(project, now):
        # This is the same check that we do on-ingest. Naively, one might think that it is superfluous. However,
        # because by design there is the potential for a digestion backlog to exist, it is possible that the update
        # of `project.quota_exceeded_until` happens only after any number of events have already passed through
        # ingestion and have entered the pipeline. Hence we double-check on-digest.

        # nothing to check (otherwise) or update on project in this case, also abort further event-processing
        return False

    project.digested_event_count += 1

    if ((project.digested_event_count >= project.next_quota_check) or
            (project.next_quota_check - project.digested_event_count > min_threshold)):

        # diff > min_threshold guards against shrunken thresholds (changed settings): if this condition holds, we've
        # been able to detect the setting-change and trigger a recheck. (in the case it's not detectable, we may at
        # worst get a "fresh quotum batch" of the new quotom size which is fine too).

        # check_for_thresholds is relatively expensive (SQL group by); we do it as little as possible

        # Notes on off-by-one:
        # * check_for_thresholds tests for "gte"; this means it will trigger once the quota is reached (not
        #   exceeded). We act accordingly by accepting this final event (returning True, count += 1) and closing the
        #   door (setting quota_exceeded_until).
        # * add_for_current=1 because we're called before the event is digested (it's not in Event.objects.filter),
        #   and because of the previous bullet we know that it will always be digested.
        states = check_for_thresholds(Event.objects.filter(project=project), now, thresholds, 1)

        until = max([below_from for (is_exceeded, below_from, _, _) in states if is_exceeded], default=None)
        until, threshold_info = max(
            [(below_from, ti) for (is_exceeded, below_from, _, ti) in states if is_exceeded],
            default=(None, None))

        check_again_after = min([check_after for (_, _, check_after, _) in states], default=1)

        project.quota_exceeded_until = until
        project.quota_exceeded_reason = json.dumps(threshold_info)

        # note on correction of `digested_event_count += 1`: as long as we don't do that between the check on
        # next_quota_check (the if-statement) and the setting (the statement below) we're good.
        project.next_quota_check = project.digested_event_count + check_again_after

    project.save()
    return True


def count_issue_periods_and_act_on_it(issue, event, timestamp):
    # See the project-version for various off-by-one notes (not reproduced here).
    #
    # We just have "unmute" as a purpose here, not "quota". I thought I'd have per-issue quota earlier (which would
    # ensure some kind of fairness within a project) but:
    #
    # * that doesn't quite work, because to determine the issue, you'd have to incur almost all of the digest cost.
    # * quota are expected to be set "high enough" anyway, i.e. only as a last line of defense against run-away
    #     clients
    # * "even if" you'd get this to work there'd be scenarios where it's useless, e.g. misbehaving groupers.
    thresholds = IssueStateManager.get_unmute_thresholds(issue)

    if thresholds and issue.digested_event_count >= issue.next_unmute_check:
        states = check_for_thresholds(Event.objects.filter(issue=issue), timestamp, thresholds)

        check_again_after = max(1, min([check_after for (_, _, check_after, _) in states], default=1))

        issue.next_unmute_check = issue.digested_event_count + check_again_after

        for (is_exceeded, until, _, (period_name, nr_of_periods, gte_threshold)) in states:
            if not is_exceeded:
                continue

            IssueStateManager.unmute(issue, triggering_event=event, unmute_metadata={"mute_until": {
                "period": period_name, "nr_of_periods": nr_of_periods, "volume": gte_threshold}})

            # In the (in the current UI impossible, and generally unlikely) case that multiple unmute conditions are
            # met simultaneously, we arbitrarily break after the first. (this makes it so that a single TurningPoint
            # is created and that the detail that there was also another reason to unmute doesn't show us, but
            # that's perfectly fine); it also matches what we do elsewhere (i.e. `IssueStateManager.unmute` where we
            # have `if is_muted`)
            break


