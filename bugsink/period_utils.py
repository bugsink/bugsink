from dateutil.relativedelta import relativedelta


DATEUTIL_KWARGS_MAP = {
    "year": "years",
    "month": "months",
    "week": "weeks",
    "day": "days",
    "hour": "hours",
    "minute": "minutes",
}


def add_periods_to_datetime(dt, nr_of_periods, period_name):
    return dt + relativedelta(**{DATEUTIL_KWARGS_MAP[period_name]: nr_of_periods})


def sub_periods_from_datetime(dt, nr_of_periods, period_name):
    return dt - relativedelta(**{DATEUTIL_KWARGS_MAP[period_name]: nr_of_periods})
