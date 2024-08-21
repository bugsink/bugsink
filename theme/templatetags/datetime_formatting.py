from django import template
from django.utils import timezone

register = template.Library()


# PAUSED FOR NOW
# reason: can we ever make better guesses (in general) than just providing iso formats?
# I'm thinking: no
# also: space-wise, there's always a window where you want all info (perhaps maybe the year). Namely: a couple of days
# ago,
#
# Further thoughts:
# you can also _decrease_ specificity when going back in time, e.g. "november 2022" or "Tuesday"

@register.filter  # expects_localtime=True) ??
def short_given_now(value):
    """
    [ ] format dates as ISO-like (or with short month notation),
        never showing more than necessary.

        chunks for consideration will be:
            time-only: when it's on the current day.
                or even: when it's on the current day or no more than a couple of hours ago.

            day and month: not on current day, but no more than (365 minus small number) ago ... or the same: boundary or a few months
                idea: if it's almost a full year ago the disambiguation will be helpful, and this also helps against confusion

    de hint met daarin de volledige datum als default dinges?
    """
    # take a look at how the standard Django filters deal with local time.
    # because I want to compare 2 local times here (e.g. to know what the date boundary is)

    # useful bits:
    now = timezone.now()  # noqa
    default_timezone = timezone.get_current_timezone()
    timezone.localtime(value, default_timezone)
