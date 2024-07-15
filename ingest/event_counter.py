from datetime import timezone, datetime

from django.db.models import Min


def _filter_for_periods(qs, period_name, nr_of_periods, now):
    from issues.models import sub_periods_from_datetime  # I'll move this soon

    if period_name == "total":
        return qs

    return qs.filter(server_side_timestamp__gte=sub_periods_from_datetime(now, nr_of_periods, period_name))


def check_for_thresholds(qs, now, thresholds):
    from issues.models import add_periods_to_datetime  # I'll move this soon
    # thresholds :: [(period_name, nr_of_periods, gte_threshold, metadata), ...]

    # we only allow UTC, and we generally use Django model fields, which are UTC, so this should be good:
    assert now.tzinfo == timezone.utc

    states_with_metadata = []

    for (period_name, nr_of_periods, gte_threshold, metadata) in thresholds:
        count = _filter_for_periods(qs, period_name, nr_of_periods, now).count()
        state = count >= gte_threshold

        if state:

            if period_name == "total":
                # when counting the 'total', there will never be a time when the condition becomes false. We
                # just pick an arbitrarily large date; we'll deal with it by the end of the myria-annum.
                # unlikely to actually end up in the DB (because it would imply the use of a quota for total).
                below_threshold_from = datetime(9999, 12, 31, 23, 59, tzinfo=timezone.utc)

            else:
                # `below_threshold_from` is the first moment in time where the condition no longer applies.
                # just get the min value of server-time over the qs:

                below_threshold_from = add_periods_to_datetime(
                    _filter_for_periods(qs, period_name, nr_of_periods, now).aggregate(
                        agg=Min('server_side_timestamp'))['agg'],
                    nr_of_periods, period_name)

        else:
            below_threshold_from = None

        states_with_metadata.append((state, below_threshold_from, metadata))

    # we return tuples of (state, below_threshold_from, metadata) where metadata is something arbitrary that can be
    # passed in (it allows us to tie back to "what caused this to be true/false?"
    # TODO: I think that in practice the metadata is always implied by the thresholds, i.e. instead of
    # passing-through we could just return the thresholds that were met.
    return states_with_metadata
