from datetime import timedelta

from . import v1, v2


class GroupingMechanism:
    def __init__(self, identifier, display_name, grouper):
        self.identifier = identifier
        self.display_name = display_name
        self.grouper = grouper


GROUPING_TRANSITION_PERIOD = timedelta(days=30)

LEGACY_GROUPING_MECHANISM = "bugsink-v1"
LATEST_GROUPING_MECHANISM = "bugsink-v2"

# I think in general it's a good idea to let legacy display names reflect the history, and have the latest name reflect
# why it's better than the previous one.
GROUPING_MECHANISMS = [
    GroupingMechanism(
        LEGACY_GROUPING_MECHANISM,
        "Original, default until v2.4.0 (July 2026)",
        v1.default_issue_grouper,
    ),
    GroupingMechanism(
        LATEST_GROUPING_MECHANISM,
        "Value-normalized (latest)",
        v2.default_issue_grouper,
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
