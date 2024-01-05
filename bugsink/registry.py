import json

from .period_counter import PeriodCounter
from .volume_based_condition import VolumeBasedCondition

from issues.models import Issue


def create_unmute_issue_handler(issue_id):
    def unmute():
        # or just push this into a classmethod
        # or make this using .update to avoid 1 of the 2 DB queries
        issue = Issue.objects.get(id=issue_id)
        issue.is_muted = False
        issue.unmute_on_volume_based_conditions = "[]"
        issue.save()

    return unmute


class PeriodCounterRegistry(object):

    def load_from_scratch(self, projects, issues, ordered_events, now_tup):
        by_project = {}
        by_issue = {}

        for project in projects:
            by_project[project.id] = PeriodCounter()

        for issue in issues:
            by_issue[issue.id] = PeriodCounter()

        for event in ordered_events:
            project_pc = by_project[event.project_id]
            project_pc.inc(event.timestamp)

            issue_pc = by_issue[event.issue_id]
            issue_pc.inc(event.timestamp)

        for issue in issues.filter(is_muted=True):
            issue_pc = by_issue[issue.id]

            unmute_vbcs = [
                VolumeBasedCondition.from_dict(vbc_s)
                for vbc_s in json.loads(issue.unmute_on_volume_based_conditions)
            ]

            for vbc in unmute_vbcs:
                issue_pc.add_event_listener(
                    period_name=vbc.period_name,
                    nr_of_periods=vbc.nr_of_periods,
                    gte_threshold=vbc.volume,
                    when_becomes_true=create_unmute_issue_handler(issue.id),
                    tup=now_tup,
                    auto_remove=True,  # unmuting is needed only once; hence auto_remove to avoid recurring unmute calls
                )

        return by_project, by_issue


# some TODOs:
#
# * quotas (per project, per issue)
