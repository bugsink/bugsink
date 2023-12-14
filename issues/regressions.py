from releases.models import ordered_releases


def is_regression(sorted_releases, fixed_at, events_at, current_event_at):
    # NOTE: linear in time with the number of releases; however, for now it's a nice reference implementation.
    # premature optimizations and the root of all evil and all that. some thoughts though:
    #
    # "if current_event_at in events_at" return False <= this could be a shortcut
    # * sorted_releases grows with time for projects, but how many 'fixed_at` can we reasonably expect?
    #       unless we even do things like release cleanup, which isn't so crazy...
    # * we need not consider anything (from sorted_releases) before the first `fixed_at` moment, because that's the
    #   first flipping of `marked_as_resolved`. this could even be done at the DB level.
    #
    marked_as_resolved = False

    for r in sorted_releases:
        if r in events_at:
            marked_as_resolved = False
        elif r in fixed_at:
            marked_as_resolved = True

        if current_event_at == r:
            return marked_as_resolved

    raise Exception("Can't find release '%s'" % current_event_at)


def issue_is_regression(issue, current_event_at):
    if not issue.is_resolved:
        return False

    if issue.is_resolved_by_next_release:
        # i.e. this is solved, but only "in the future". The assumption (which is true in our code) here is: once this
        # point is reached, all "actually seen releases" will have already been accounted for.
        return False

    if not issue.project.has_releases:
        return True  # i.e. `return issue.is_resolved`, which is True if this point is reached.

    sorted_releases = [r.version for r in ordered_releases(project=issue.project)]
    fixed_at = issue.get_fixed_at()
    events_at = issue.get_events_at()

    return is_regression(sorted_releases, fixed_at, events_at, current_event_at)


def is_regression_2(sorted_releases, fixed_at, events_at, current_event_at):
    # AKA is_regression_with_fixed_later_info, i.e. returns a tuple of which the second element expresses something
    # about this happening in the middle of your timeline. On a second viewing I'm a lot less sure that this is useful
    # than I was previously. I mean: if you marked something as fixed (explicitly) on some old feature branch, and it
    # reoccurs, you want to know that. The fact that you've also marked it as fixed on a later branch doesn't change
    # that.

    # for lack of a better name; I want to express this idea somewhere first; let's see how we utilize it in actual code
    # later; hence also copy/pasta
    fixed_at = fixed_at[:]
    marked_as_resolved = False

    for r in sorted_releases:
        if r in events_at:
            marked_as_resolved = False
        elif r in fixed_at:
            marked_as_resolved = True
            fixed_at.remove(r)

        if current_event_at == r:
            return marked_as_resolved, len(fixed_at) > 0

    raise Exception("Can't find release '%s'" % current_event_at)
