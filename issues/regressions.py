def is_regression(sorted_releases, fixed_at, events_at, current_event_at):
    # NOTE: linear in time with the number of releases; however, for now it's a nice reference implementation.
    # premature ... and the root of all evil. some thoughts though:
    # * sorted_releases grows with time for projects, but how many 'fixed_at` can we reasonably expect?
    #       unless we even do things like release cleanup, which isn't so crazy...
    # * we need not consider anything (from sorted_releases) before the first `fixed_at` moment, because that's the
    #   first flipping of `marked_as_resolved`
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
