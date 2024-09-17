from releases.models import ordered_releases

# note that we don't check for is_muted anywhere in this file; this is because issues that are muted are unresolved (the
# combination of muted & resolved is illegal and we enforce this elsewhere) and the unresolved case is trivially not a
# regression. (first guard clause in `issue_is_regression`)


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
    """
    Given that a new event has just occurred, is this issue a regression?
    `current_event_at` is the release at which the event occurred.

    Must be called after `is_resolved_by_next_release`-handling for new releases (i.e. `create_release_if_needed`) to
    ensure the logic surrounding `issue.is_resolved_by_next_release` is correct.
    """

    if not issue.is_resolved:
        # unresolved issues can't be regressions by definition
        return False

    if issue.is_resolved_by_next_release:
        # if issue.is_resolved and issue.is_resolved_by_next_release <= implied because of the first guard clause.
        # Which is to say the `is_resolved` marker is there, but another field qualifies it as "only in the future".
        # Which means that seeing new events does not imply a regression, because that future hasn't arrived yet.
        return False

    if not issue.project.has_releases:
        # the simple case: no releases means that seeing new events implies a regression if the issue.is_resolved, which
        # is True given the first guard clause.
        return True

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
