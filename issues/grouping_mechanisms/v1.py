from django.utils.encoding import force_str

from .building_blocks.v1 import get_title_for_exception_type_and_value


def default_issue_grouper(data, calculated_type, calculated_value):
    title = get_title_for_exception_type_and_value(calculated_type, calculated_value)
    transaction = force_str(data.get("transaction") or "<no transaction>")
    return title + " ⋄ " + transaction
