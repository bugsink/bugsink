def is_regression(sorted_releases, fixed_at, issues_at, current_issue_at):
    # NOTE: linear in time with the number of releases; however, for now it's a nice reference implementation.
    marked_as_resolved = False

    for r in sorted_releases:
        if r in issues_at:
            marked_as_resolved = False
        elif r in fixed_at:
            marked_as_resolved = True

        if current_issue_at == r:
            return marked_as_resolved

    raise Exception("Can't find release '%s'" % current_issue_at)
