from datetime import timezone, datetime

from django.db.models import Min

from bugsink.period_utils import add_periods_to_datetime, sub_periods_from_datetime


def _filter_for_periods(qs, period_name, nr_of_periods, now):
    if period_name == "total":
        return qs

    return qs.filter(digested_at__gte=sub_periods_from_datetime(now, nr_of_periods, period_name))


def check_for_thresholds(qs, now, thresholds, add_for_current=0):
    # thresholds :: [(period_name, nr_of_periods, gte_threshold), ...]
    # returns [(state, below_threshold_from, check_again_after, (period_name, nr_of_periods, gte_threshold)), ...]

    # This function does aggregation, so it's reasonably expensive (I haven't measured exactly, but it seems to be at
    # least as expensive per-call as the whole of the rest of digestion). We solve this by not calling it often, using
    # the `check_again_after` mechanism (which relies on simple counting, and the fact that a threshold for any given
    # period of time will certainly not be crossed sooner than that the number of observations over _any_ time period
    # exceeds the given threshold. The amorization then happens over the difference between the threshold and the
    # actually observed number of events over the relevant time-period; in other words, unless for some weird reason you
    # are consitently super-close to the quota but not over-quota the amortization will happen over a reasonable
    # fraction of the quota, and if the quota is reasonably high (which is the only relevant-for-performance case
    # anyway) this means the cost will be amortized away. (e.g. quota of 1_000; a check every 100 events in a bad case).
    # The only relevant cost that this mechanism thus adds is the per-project counting of digested events.

    # we only allow UTC, and we generally use Django model fields, which are UTC, so this should be good:
    assert now.tzinfo == timezone.utc

    states = []

    for (period_name, nr_of_periods, gte_threshold) in thresholds:
        count = _filter_for_periods(qs, period_name, nr_of_periods, now).count() + add_for_current
        state = count >= gte_threshold

        if state:

            if period_name == "total":
                # when counting the 'total', there will never be a time when the condition becomes false. We
                # just pick an arbitrarily large date; we'll deal with it by the end of the myria-annum.
                # unlikely to actually end up in the DB (because it would imply the use of a quota for total).
                below_threshold_from = datetime(9999, 12, 31, 23, 59, tzinfo=timezone.utc)

            else:
                # `below_threshold_from` is the first moment in time where the condition no longer applies. Assuming
                # the present function is called "often enough" (i.e is called for the moment the switch to state=True
                # happens, and not thereafter), there will be _excactly_ `gte_threshold` items in the qs (potentially
                # with 1 implied one if `add_for_current` applies). Taking the min of those and adding the time period
                # brings us to the point in time where the condition will become False again.
                #
                # (The assumption of "often enough, and no more" holds for us because for quota we stop accepting events
                # once the quota is met; for muted we remove the vbc once unmuted). For the "overshoot" case (see tests,
                # not really expected) this has the consequence of seeing a result that is "too old", and hence going
                # back to accepting too soon. But this is self-correcting, so no need to deal with it.
                below_threshold_from = add_periods_to_datetime(
                    _filter_for_periods(qs, period_name, nr_of_periods, now).aggregate(
                        agg=Min('digested_at'))['agg'] or now,  # `or now` to handle funny `gte_threshold==0`
                    nr_of_periods, period_name)

        else:
            below_threshold_from = None

        check_again_after = gte_threshold - count

        states.append((state, below_threshold_from, check_again_after, (period_name, nr_of_periods, gte_threshold)))

    return states
