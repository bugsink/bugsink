from issues.utils import get_title_for_exception_type_and_value


def default_issue_grouper(calculated_type, calculated_value, transaction):
    title = get_title_for_exception_type_and_value(calculated_type, calculated_value)
    return title + " ⋄ " + transaction
