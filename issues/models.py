import json
import uuid

from django.db import models


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'
    hash = models.CharField(max_length=32, blank=False, null=False)

    # TODO: we should get rid of an M2M table by making this a FK from the other side
    events = models.ManyToManyField("events.Event")

    # fields related to resolution:
    # what does this mean for the release-based use cases? it means what you filter on.
    # it also simply means: it was "marked as resolved" after the last regression (if any)
    is_resolved = models.BooleanField(default=False)
    is_resolved_by_next_release = models.BooleanField(default=False)
    fixed_at = models.TextField(blank=False, null=False, default='[]')
    events_at = models.TextField(blank=False, null=False, default='[]')

    def get_absolute_url(self):
        return f"/issues/issue/{ self.id }/event/last/"

    def parsed_data(self):
        # TEMP solution; won't scale
        return json.loads(self.events.first().data)

    def get_main_exception(self):
        # TODO: refactor (its usages) to a (filled-on-create) field

        # Note: first event, last exception

        # We call the last exception in the chain the main exception because it's the one you're most likely to care
        # about. I'd roughly distinguish 2 cases for reraising:
        #
        # 1. intentionally rephrasing/retyping exceptions to more clearly express their meaning. In that case you
        #    certainly care more about the rephrased thing than the original, that's the whole point.
        #
        # 2. actual "accidents" happening while error-handling. In that case you care about the accident first (bugsink
        #    is a system to help you think about cases that you didn't properly think about in the first place),
        #    although you may also care about the root cause. (In fact, sometimes you care more about the root cause,
        #    but I'd say you'll have to yak-shave your way there).

        parsed_data = json.loads(self.events.first().data)
        exc = parsed_data.get("exception", {"values": []})
        values = exc["values"]  # required by the json spec, so can be done safely
        return values[-1] if values else {}

    def title(self):
        # TODO: refactor to a (filled-on-create) field
        main_exception = self.get_main_exception()
        return main_exception.get("type", "none") + ": " + main_exception.get("value", "none")

    def get_fixed_at(self):
        return json.loads(self.fixed_at)

    def get_events_at(self):
        return json.loads(self.events_at)

    def add_fixed_at(self, release):
        fixed_at = self.get_fixed_at()
        if release.version not in fixed_at:
            fixed_at.append(release.version)
            self.fixed_at = json.dumps(fixed_at)

    def occurs_in_last_release(self):
        return False  # TODO actually implement (and then: implement in a performant manner)


class IssueResolver(object):
    """basically: a namespace"""

    @staticmethod
    def resolve(issue):
        issue.is_resolved = True

    @staticmethod
    def resolve_by_latest(issue):
        issue.is_resolved = True
        issue.add_fixed_at(issue.project.get_latest_release())

    @staticmethod
    def resolve_by_next(issue):
        issue.is_resolved = True
        issue.is_resolved_by_next_release = True

    @staticmethod
    def reopen(issue):
        issue.is_resolved = False
        issue.is_resolved_by_next_release = False  # ?? echt?
        # TODO and what about fixed_at ?
