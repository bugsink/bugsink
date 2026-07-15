from datetime import timedelta

from . import v1, v2


class GroupingMechanism:
    def __init__(self, identifier, display_name, grouper):
        self.identifier = identifier
        self.display_name = display_name
        self.grouper = grouper


GROUPING_TRANSITION_PERIOD = timedelta(days=30)

MECHANISM_INDEPENDENT_GROUPING = "none"
BUGSINK_GROUPING_V1 = "bugsink-v1"
BUGSINK_GROUPING_V2 = "bugsink-v2"
CURRENT_GROUPING_MECHANISM = BUGSINK_GROUPING_V2

# I think in general it's a good idea to let legacy display names reflect the history, and have the latest name reflect
# why it's better than the previous one.
GROUPING_MECHANISMS = [
    GroupingMechanism(
        BUGSINK_GROUPING_V1,
        "Original, default until v2.4.0 (July 2026)",
        v1.default_issue_grouper,
    ),
    GroupingMechanism(
        BUGSINK_GROUPING_V2,
        "Value-normalized (latest)",
        v2.default_issue_grouper,
    ),
]

GROUPING_MECHANISM_CHOICES = [
    (mechanism.identifier, mechanism.display_name)
    for mechanism in GROUPING_MECHANISMS
]
GROUPING_CHOICES = [
    # more precisely "explicit fingerprint not containing the default grouper" but that's overly verbose in practice.
    (MECHANISM_INDEPENDENT_GROUPING, "Mechanism-independent (explicit fingerprint)"),
] + GROUPING_MECHANISM_CHOICES


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
