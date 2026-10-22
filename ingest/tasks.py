import os
import logging
import json
from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone as django_timezone

from bugsink.app_settings import get_settings
from bugsink.transaction import immediate_atomic, delay_on_commit
from snappea.decorators import shared_task
from phonehome.models import Installation
from projects.models import Project
from sentry.minidump import merge_minidump_event
from issues.models import Issue, IssueStateManager, TurningPoint, TurningPointKind
from issues.regressions import issue_is_regression
from issues.utils import get_type_and_value_for_data, get_denormalized_fields_for_data
from events.models import Event
from events.retention import evict_for_max_events, should_evict, EvictionCounts
from events.usage import record_event_counts
from releases.models import create_release_if_needed
from alerts.tasks import send_new_issue_alert, send_regression_alert
from compat.timestamp import parse_timestamp
from tags.models import digest_tags

from .digestion import (
    GroupingPath,
    count_installation_periods_and_act_on_it,
    count_issue_periods_and_act_on_it,
    count_project_periods_and_act_on_it,
    create_grouping,
    get_grouping_path_for_event,
    handle_zero_retention,
    is_quota_still_exceeded,
    update_issue_counts,
    validate_event_data,
)
from .filestore import get_filename_for_event_id

logger = logging.getLogger("bugsink.ingest")


@shared_task
def digest(event_id, event_metadata):
    if "ingestion_id" in event_metadata:
        ingestion_id = event_metadata["ingestion_id"]  # the normal case
    else:
        ingestion_id = event_id  # for bugsink<=2.0.11 events in-transit in snappea queue cross version upgrade

    with open(get_filename_for_event_id(ingestion_id), "rb") as f:
        event_data = json.loads(f.read().decode("utf-8"))
        opened = [get_filename_for_event_id(ingestion_id)]

    if event_metadata.get("has_minidump"):
        with open(get_filename_for_event_id(ingestion_id, filetype="minidump"), "rb") as f:
            minidump_bytes = f.read()
            opened += [get_filename_for_event_id(ingestion_id, filetype="minidump")]
    else:
        minidump_bytes = None

    try:
        project = Project.objects.filter(pk=event_metadata["project_id"], is_deleted=False).first()
        if project is None:
            return
        if handle_zero_retention(project):
            return

        # Quota-shedding must be done before immediate_atomic is entered such that it can be done in parallel, see #494
        # NOTE `now` is separate from `digested_at` in digest_event. Does that mean clock-differences lead to shedding
        # too much? No: if this were so, it would only be so by virtue of the quota expiring b/c our processing was
        # delayed. Also realise: any event literally arriving (at ingest) _now_ would also not make it.
        # The reverse case also works (checking early cannot let an event bypass the quota: digest_event checks again)
        now = django_timezone.now()
        installation = Installation.objects.get()
        if is_quota_still_exceeded(installation, now) or is_quota_still_exceeded(project, now):
            return

        if get_settings().VALIDATE_ON_DIGEST in ["warn", "strict"]:
            validate_event_data(event_data, get_settings().VALIDATE_ON_DIGEST)

        if minidump_bytes is not None:
            # we merge after validation: validation is about what's provided _externally_, not our own merging.
            # We parse before entering immediate_atomic so this work doesn't hold the database write lock.
            # TODO error handling
            merge_minidump_event(event_data, minidump_bytes, project)

        digest_event(event_metadata, event_data)
    except ValidationError as e:
        logger.warning("ValidationError in digest", exc_info=e)
    finally:
        # "Robustly" remove all opened files (don't stop on failure), but still report any errors at the end
        errors = []
        for filename in opened:
            try:
                os.unlink(filename)
            except FileNotFoundError as e:
                errors.append(e)
        if errors:
            raise Exception(errors)


@immediate_atomic()
def digest_event(event_metadata, event_data, digested_at=None):
    # ingested_at is passed from the point-of-ingestion; digested_at is determined here. Because this happens inside
    # `immediate_atomic`, we know digestions are serialized, and assuming non-decreasing server clocks, not decrea-
    # sing. (no so for ingestion times: clock-watching happens outside the snappe transaction, and threading in the
    # foreman is another source of shuffling).
    #
    # Because of this property we use digested_at for eviction and quota, and, because quota is a VBC-based and so
    # is unmuting, in all ummuting-related checks. This saves us from having to precisely reason about edge-cases
    # for non-increasing time, and the drawbacks are minimal, because the differences in time between ingest and
    # digest are assumed to be relatively small, and as a user you don't really care (to the second) which
    # timestamps trigger the quota/eviction.
    #
    # For other user-facing elements in the UI we prefer ingested_at though, because that's closer to the time
    # something actually happened, and that's usually what you care for while debugging.
    ingested_at = parse_timestamp(event_metadata["ingested_at"])
    digested_at = datetime.now(timezone.utc) if digested_at is None else digested_at  # explicit passing: test only

    try:
        project = Project.objects.get(pk=event_metadata["project_id"], is_deleted=False)
    except Project.DoesNotExist:
        # we may get here if the project was deleted after the event was ingested, but before it was digested
        # (covers both "deletion in progress (is_deleted=True)" and "fully deleted").
        return

    # Recheck inside the transaction: retention may have changed since the task's early check.
    if handle_zero_retention(project):
        return

    installation = Installation.objects.get()
    if (not count_installation_periods_and_act_on_it(installation, digested_at)
            or not count_project_periods_and_act_on_it(project, digested_at)):

        return  # if over-quota: just return (any cleanup is done calling-side)

    # I resisted the temptation to put `get_denormalized_fields_for_data` in an if-statement: you basically "always"
    # need this info... except when duplicate event-ids are sent. But the latter is the exception, and putting this
    # in an if-statement would require more rework (and possibly extra queries) than it's worth.
    denormalized_fields = get_denormalized_fields_for_data(event_data)

    # the 3 lines below are suggestive of a further inlining of the get_type_and_value_for_data function
    calculated_type, calculated_value = get_type_and_value_for_data(event_data)
    denormalized_fields["calculated_type"] = calculated_type
    denormalized_fields["calculated_value"] = calculated_value

    grouping_path, path_context = get_grouping_path_for_event(project, event_data, digested_at)

    if grouping_path in [GroupingPath.FOUND, GroupingPath.ATTACH]:
        if grouping_path == GroupingPath.FOUND:
            grouping, = path_context
        else:
            key_with_mechanism, grouping_to_attach_to = path_context
            grouping = create_grouping(
                event_metadata["project_id"], key_with_mechanism, grouping_to_attach_to.issue)

        issue = grouping.issue
        issue_created = False

        # update the denormalized fields; calculated_type/value track the latest event so the issue title
        # reflects the most recent exception (otherwise it stays frozen to the first event's message).
        issue.last_seen = ingested_at
        issue.digested_event_count += 1
        issue.calculated_type = calculated_type
        issue.calculated_value = calculated_value

    elif grouping_path == GroupingPath.NEW:
        key_with_mechanism, = path_context

        # we don't have Project.issue_count here ('premature optimization') so we just do an aggregate instead.
        max_current = Issue.objects.filter(project_id=event_metadata["project_id"]).aggregate(
            Max("digest_order"))["digest_order__max"]
        issue_digest_order = max_current + 1 if max_current is not None else 1

        # at this point in the code, "new grouper" implies "new issue", because manual information ("this grouper is
        # actually part of some other issue") can by definition not yet have been specified.
        issue = Issue.objects.create(
            digest_order=issue_digest_order,
            project_id=event_metadata["project_id"],
            first_seen=ingested_at,
            last_seen=ingested_at,
            digested_event_count=1,
            stored_event_count=0,  # we increment this below
            **denormalized_fields,
        )
        issue_created = True

        grouping = create_grouping(event_metadata["project_id"], key_with_mechanism, issue)

    # +1 because we're about to add one event.
    project_stored_event_count = project.stored_event_count + 1

    if should_evict(project, digested_at, project_stored_event_count):
        # Note: I considered pushing this into some async process, but it makes reasoning much harder, and it's
        # doubtful whether it would help, because in the end there's just a single pipeline of ingested-related
        # stuff todo, might as well do the work straight away. Similar thoughts about pushing this into something
        # cron-like. (not exactly the same, because for cron-like time savings are possible if the cron-likeness
        # causes the work to be outside of the 'rush hour' -- OTOH this also introduces a lot of complexity about
        # "what is a limit anyway, if you can go either over it, or work is done before the limit is reached")
        evicted = evict_for_max_events(project, digested_at, project_stored_event_count)

        # digest_event() is responsible for this update because we have "issue" open (i.e. to "save a query" /
        # "avoid updating stale objects")
        update_issue_counts({k: cnt for (k, cnt) in evicted.per_issue.items() if k != issue.id})
    else:
        evicted = EvictionCounts(0, {})

    # +1 because we're about to add one event
    issue.stored_event_count = issue.stored_event_count + 1 - evicted.per_issue.get(issue.id, 0)
    project.stored_event_count = project_stored_event_count - evicted.total
    if issue_created:
        project.issue_count += 1
        project.save(update_fields=["stored_event_count", "issue_count"])
    else:
        project.save(update_fields=["stored_event_count"])

    event, event_created = Event.from_ingested(
        event_metadata,
        digested_at,
        issue.digested_event_count,
        project.digested_event_count,
        issue.stored_event_count,
        issue,
        grouping,
        event_data,
        denormalized_fields,
    )
    if not event_created:
        # This is a weird case that can happen when a client sends the same event_id with data different enough to
        # create a new issue. I've run into it while debugging by editing a sample event without updating the ID or
        # using send_json --fresh-id. Raising ValidationError rolls back the surrounding transaction and handles the
        # duplicate as invalid client input.
        #
        # Validating by letting the DB raise an exception, and only after taking some other actions already, is not
        # "by the book" (some book), but it's the most efficient way of doing it when your basic expectation is that
        # multiple events with the same event_id "don't happen" (i.e. are the result of badly misbehaving clients).
        # Note: given the ordering here this may hit after an eviction; that was not imagined (but will still work,
        # albeit with considerable wasted work in that scenario).
        raise ValidationError("Event already exists", code="event_already_exists")

    record_event_counts(project, issue, digested_at, event.digest_order)

    release, _ = create_release_if_needed(project, event.release, event.ingested_at, issue)

    if issue_created:
        TurningPoint.objects.create(
            project=project,
            issue=issue, triggering_event=event, timestamp=ingested_at,
            kind=TurningPointKind.FIRST_SEEN)
        event.never_evict = True

        if project.alert_on_new_issue:
            delay_on_commit(send_new_issue_alert, str(issue.id))

    else:
        # new issues cannot be regressions by definition, hence this is in the 'else' branch
        if issue_is_regression(issue, event.release):
            TurningPoint.objects.create(
                project=project,
                issue=issue, triggering_event=event, timestamp=ingested_at,
                kind=TurningPointKind.REGRESSED)
            event.never_evict = True

            if project.alert_on_regression:
                delay_on_commit(send_regression_alert, str(issue.id))

            IssueStateManager.reopen(issue)

        # note that while digesting we _only_ care about .is_muted to determine whether unmuting (and alerting about
        # unmuting) should happen, whether as a result of a VBC or 'after time'. Somewhat counter-intuitively, a
        # 'muted' issue is thus not treated as something to more deeply ignore than an unresolved issue (and in
        # fact, conversely, it may be more loud when the for/until condition runs out). This is in fact analogous to
        # "resolved" issues which are _also_ treated with more "suspicion" than their unresolved counterparts.
        if issue.is_muted and issue.unmute_after is not None and digested_at > issue.unmute_after:
            # note that unmuting on-ingest implies that issues that no longer occur stay muted. I'd say this is what
            # you want: things that no longer happen should _not_ draw your attention, and if you've nicely moved
            # some issue away from the "Open" tab it should not reappear there if a certain amount of time passes.
            # Thus, unmute_after should more completely be called unmute_until_events_happen_after but that's a bit
            # long. Phrased slightly differently: you basically click the button saying "I suppose this issue will
            # self-resolve in x time; notify me if this is not the case"
            IssueStateManager.unmute(
                issue, triggering_event=event,
                unmute_metadata={"mute_for": {"unmute_after": issue.unmute_after}})

    count_issue_periods_and_act_on_it(issue, event, digested_at)

    if event.never_evict:
        # as a sort of poor man's django-dirtyfields (which we haven't adopted for simplicity's sake) we simply do
        # this manually for a single field; we know that if never_evict has been set, it's always been set after the
        # .create call, i.e. its results still need to be saved. We accept the cost of the extra .save call, since
        # TurningPoints are relatively rare (and hence so is this setting of `never_evict` and the associated save
        # call)
        event.save()

    if release.version + "\n" not in issue.events_at:
        issue.events_at += release.version + "\n"

    issue.save()

    # intentionally at the end: possible future optimization is to push this out of the transaction (or even use
    # a separate DB for this)
    digest_tags(event_data, event, issue)
