from dataclasses import dataclass
from datetime import timedelta

from . import after_2_4_0, up_until_2_4_0


@dataclass(frozen=True)
class GroupingMechanism:
    identifier: str
    display_name: str
    grouper: object


GROUPING_TRANSITION_PERIOD = timedelta(days=30)

LEGACY_GROUPING_MECHANISM = "bugsink-up-until-v2.4.0"
LATEST_GROUPING_MECHANISM = "bugsink-after-v2.4.0"

GROUPING_MECHANISMS = [
    GroupingMechanism(
        LEGACY_GROUPING_MECHANISM,
        "Up until v2.4.0 (July 2026)",
        up_until_2_4_0.default_issue_grouper,
    ),
    GroupingMechanism(
        LATEST_GROUPING_MECHANISM,
        "After v2.4.0 (July 2026)",
        after_2_4_0.default_issue_grouper,
    ),
]

GROUPING_MECHANISM_CHOICES = [
    (mechanism.identifier, mechanism.display_name)
    for mechanism in GROUPING_MECHANISMS
]


def get_grouping_mechanism(identifier):
    for mechanism in GROUPING_MECHANISMS:
        if mechanism.identifier == identifier:
            return mechanism

    raise ValueError(f"Unknown grouping mechanism: {identifier}")


def get_next_grouping_mechanism(identifier):
    for i, mechanism in enumerate(GROUPING_MECHANISMS):
        if mechanism.identifier == identifier:
            if i + 1 == len(GROUPING_MECHANISMS):
                return None
            return GROUPING_MECHANISMS[i + 1]

    raise ValueError(f"Unknown grouping mechanism: {identifier}")
