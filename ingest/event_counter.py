from datetime import timezone, datetime

from django.db.models import Min

from bugsink.period_utils import add_periods_to_datetime, sub_periods_from_datetime
from bugsink.utils import assert_


def _filter_for_periods(qs, period_name, nr_of_periods, now):
    if period_name == "total":
        return qs

    return qs.filter(digested_at__gte=sub_periods_from_datetime(now, nr_of_periods, period_name))


def check_for_thresholds(qs, now, thresholds, add_for_current=0):
    # thresholds :: [(period_name, nr_of_periods, gte_threshold), ...]
    # returns [(state, below_threshold_from, check_again_after, (period_name, nr_of_periods, gte_threshold)), ...]

    # This function does (or did) aggregation, so it might be expensive (haven't measured exactly, but it was previously
    # at least as expensive as the whole of the rest of digestion). We solve this by not calling it often, using
    # the `check_again_after` mechanism (which relies on simple counting, and the fact that a threshold for any given
    # period of time will certainly not be crossed sooner than that the number of observations over _any_ time period
    # exceeds the given threshold. The amorization then happens over the difference between the threshold and the
    # actually observed number of events over the relevant time-period; in other words, unless for some weird reason you
    # are consitently super-close to the quota but not over-quota the amortization will happen over a reasonable
    # fraction of the quota, and if the quota is reasonably high (which is the only relevant-for-performance case
    # anyway) this means the cost will be amortized away. (e.g. quota of 1_000; a check every 100 events in a bad case).
    # The only relevant cost that this mechanism thus adds is the per-project counting of digested events.

    # This function looks at event.project_digest_order to determine how many events have been seen in a given period.
    # This is, in the light of evictions (and deletions), an approximation only. We'll leave the proof of why and how
    # much better than counting events this is as an exercise to the reader. If we ever want to go even more precise,
    # we'll have to move to a bucketing counting scheme rather than rolling counters.

    # we only allow UTC, and we generally use Django model fields, which are UTC, so this should be good:
    assert_(now.tzinfo == timezone.utc)

    states = []

    for (period_name, nr_of_periods, gte_threshold) in thresholds:
        qs_for_period = _filter_for_periods(qs, period_name, nr_of_periods, now)

        # Hits index: (project, digested_at); project_digest_order is the tie-breaker and makes tests make sense.
        first_in_period = (
            qs_for_period.exclude(project_digest_order__isnull=True)
            .order_by('digested_at', 'project_digest_order').first())

        if first_in_period is None:
            total_events_in_period = add_for_current
        elif first_in_period.project_digest_order is None:
            # Fall back to the pre-project_digest_order behavior.
            total_events_in_period = qs_for_period.count() + add_for_current
        else:
            # will exist (implied by 'first'), and will have a project_digest_order (because only _older_ might not)
            last_in_period = (qs_for_period.exclude(project_digest_order__isnull=True)
                              .order_by('-digested_at', '-project_digest_order').first())

            total_events_in_period = (last_in_period.project_digest_order - first_in_period.project_digest_order
                                      + 1 + add_for_current)  # +1: not the difference, but the count incl. both ends

        exceeded = total_events_in_period >= gte_threshold

        if exceeded:
            if period_name == "total":
                # when counting the 'total', there will never be a time when the condition becomes false. We
                # just pick an arbitrarily large date; we'll deal with it by the end of the myria-annum.
                # unlikely to actually end up in the DB (because it would imply the use of a quota for total).
                below_threshold_from = datetime(9999, 12, 31, 23, 59, tzinfo=timezone.utc)

            else:
                # `below_threshold_from` is the first moment in time where the condition no longer applies. Assuming
                # the present function is called "often enough" (i.e is called for the moment the switch to
                # threshold_exceeded happens, and not thereafter), there will be _excactly_ `gte_threshold` items in the
                # qs. Taking the min of those and adding the time period brings us to the point in time where the
                # condition will become False again.
                #
                # (The assumption of "often enough, and no more" holds for us because for quota we stop accepting events
                # once the quota is met; for muted we remove the vbc once unmuted). For the "overshoot" case (see tests,
                # not really expected) this has the consequence of seeing a result that is "too old", and hence going
                # back to accepting too soon. But this is self-correcting, so no need to deal with it.
                #
                # `or now` to handle funny `gte_threshold==0`
                observed_period_start = qs_for_period.aggregate(agg=Min('digested_at'))['agg'] or now
                below_threshold_from = add_periods_to_datetime(observed_period_start, nr_of_periods, period_name)

        else:
            below_threshold_from = None

        check_again_after = gte_threshold - total_events_in_period

        states.append((exceeded, below_threshold_from, check_again_after, (period_name, nr_of_periods, gte_threshold)))

    return states
