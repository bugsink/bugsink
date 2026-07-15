from django.utils.encoding import force_str

from sentry.at_597d25951d00.grouping.strategies.message import normalize_message_for_grouping

from .building_blocks.v1 import get_title_for_exception_type_and_value


def default_issue_grouper(data, calculated_type, calculated_value):
    calculated_value = normalize_message_for_grouping(force_str(calculated_value))
    return get_title_for_exception_type_and_value(calculated_type, calculated_value)
