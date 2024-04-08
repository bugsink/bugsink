from django.core.management.base import BaseCommand
import uuid

import random
from datetime import datetime, timezone

from django.conf import settings

from performance.bursty_data import generate_bursty_data, buckets_to_points_in_time
from projects.models import Project
from issues.models import Issue, Grouping
from events.models import Event


class Command(BaseCommand):
    help = "..."

    def handle(self, *args, **options):
        if "performance" not in str(settings.DATABASES["default"]["NAME"]):
            raise ValueError("This command should only be run on the performance-test database")

        Project.objects.all().delete()
        Grouping.objects.all().delete()
        Issue.objects.all().delete()
        Event.objects.all().delete()

        # as a first approach, let's focus on a 'typical' (whatever that means) local setup (not hosted), for a small
        # team.  maybe 10 people would work on max 10 projects. let's assume we have 10k per-project limits for events
        # set up. and let's assume 100 issues per project (far from inbox-zero, approach bug-sewer territory)
        #
        projects = [Project.objects.create(name="project %s" % i) for i in range(10)]
        issues_by_project = {}

        for p in projects:
            issues_by_project[p.id] = []
            for i in range(100):
                issues_by_project[p.id].append(Issue.objects.create(project=p))
                Grouping.objects.create(
                    project=p,
                    grouping_key="grouping key %d" % i,
                    issue=issues_by_project[p.id][i],
                )

        # now we have 10 projects, each with 100 issues. let's create 10k events for each project.
        for p in projects:
            print("loading 10k events for project", p.name)
            points = buckets_to_points_in_time(
                generate_bursty_data(num_buckets=350, expected_nr_of_bursts=10),
                datetime(2020, 10, 15, tzinfo=timezone.utc),
                datetime(2021, 10, 15, 10, 5, tzinfo=timezone.utc),
                10_000,
            )

            for i, point in enumerate(points):
                if i % 1_000 == 0:
                    print("loaded", i, "events")

                # note: because we use such minimal (non-data-containing) events here, the setup in the below may
                # actually not be representative of real world performance.
                Event.objects.create(
                    project=p,
                    issue=random.choice(issues_by_project[p.id]),
                    server_side_timestamp=point,
                    timestamp=point,
                    event_id=uuid.uuid4().hex,
                    has_exception=True,
                    has_logentry=True,
                    data="{}",
                )
