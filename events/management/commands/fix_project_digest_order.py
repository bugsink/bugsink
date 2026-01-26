import datetime
from django.core.management.base import BaseCommand

from bugsink.transaction import immediate_atomic

from projects.models import Project
from events.models import Event


class Command(BaseCommand):
    help = """Set the project_digest_order field on all Events that lack it; as a command, since it may be expensive."""

    def fix_project_digest_order_for_project(self, project):
        # this script makes a best-effort guess at project_digest_order; best-effort, because in the light of evictions
        # such information can not be fully reconstructed. What we _do_ know: issue-level digest_order. We use this info
        # to establish a lower bound (going up through all digested events) and upper bound (going down) and then
        # "middle" (weighted middle) these values.

        by_issue_going_up = {}
        by_issue_going_down = {}

        results_going_up = {}
        results_going_down = {}

        # Re-monotomize:
        seen_digested_ats = {}
        for d in (Event.objects.filter(project=project, project_digest_order__isnull=True)
                  .order_by("issue_id", "digest_order")
                  .values("id", "digested_at", "digest_order", "issue_id")):

            if d["issue_id"] not in seen_digested_ats:
                seen_digested_ats[d["issue_id"]] = datetime.datetime.min.replace(tzinfo=d["digested_at"].tzinfo)

            if d["digested_at"] < seen_digested_ats[d["issue_id"]]:
                time_delta = seen_digested_ats[d["issue_id"]] - d["digested_at"]
                print(
                    f"Re-monotomizing digested_at for event {d['id']} to "
                    f"{seen_digested_ats[d['issue_id']]} (was {d['digested_at']}, delta {time_delta})")

                Event.objects.filter(id=d["id"]).update(digested_at=seen_digested_ats[d["issue_id"]])
            else:
                seen_digested_ats[d["issue_id"]] = d["digested_at"]

        # UP
        current = 0
        for d in (
                Event.objects.filter(project=project, project_digest_order__isnull=True)
                .order_by("digested_at", "digest_order")
                .values("id", "digest_order", "issue_id")):

            if d["issue_id"] not in by_issue_going_up:
                by_issue_going_up[d["issue_id"]] = 0

            delta = d["digest_order"] - by_issue_going_up[d["issue_id"]]
            assert delta >= 1
            by_issue_going_up[d["issue_id"]] = d["digest_order"]

            current += delta
            results_going_up[d["id"]] = current

        # DOWN
        if Event.objects.filter(project=project).exclude(project_digest_order__isnull=True).count():
            current = Event.objects.filter(project=project).exclude(project_digest_order__isnull=True). \
                        order_by("digested_at").first().project_digest_order
        else:
            current = project.digested_event_count + 1

        for d in (
                Event.objects.filter(project=project, project_digest_order__isnull=True)
                .order_by("-digested_at", "-digest_order")
                .values("id", "digest_order", "issue_id")):

            if d["issue_id"] not in by_issue_going_down:
                by_issue_going_down[d["issue_id"]] = d["digest_order"] + 1  # +1 for "the next unseen"

            delta = d["digest_order"] - by_issue_going_down[d["issue_id"]]
            assert delta <= -1
            by_issue_going_down[d["issue_id"]] = d["digest_order"]

            current += delta
            results_going_down[d["id"]] = current

        # CONNECT THE IDEAS:
        total = len(results_going_up)
        prev = 0

        for i, k in enumerate(sorted(results_going_up, key=lambda x: results_going_up[x])):
            weight_towards_end = (i + .5) / total if total > 0 else 0

            lo = results_going_up[k]
            hi = results_going_down[k]

            picked = lo + round((hi - lo) * weight_towards_end)

            picked = max(picked, prev + 1)  # weighting trick should never result in non-monotonic values
            prev = picked
            assert picked >= lo and picked <= hi, (lo, hi, picked)

            Event.objects.filter(id=k).update(project_digest_order=picked)

    def handle(self, *args, **options):
        for project in Project.objects.all():
            self.stdout.write(f"Fixing project_digest_order for project {project.id} ({project.name})")

            # global lock given the complexity of what we do (won't work e.g. with simultaneous evictions)
            with immediate_atomic():
                self.fix_project_digest_order_for_project(project)
