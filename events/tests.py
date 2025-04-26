import json
import datetime

from django.test import TestCase as DjangoTestCase
from unittest import TestCase as RegularTestCase
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership
from issues.models import Issue
from issues.factories import denormalized_issue_fields

from .factories import create_event
from .retention import (
    eviction_target, should_evict, evict_for_max_events, get_epoch_bounds_with_irrelevance, filter_for_work)
from .utils import annotate_with_meta

User = get_user_model()


class ViewTests(TransactionTestCase):
    # we start with minimal "does this show something and not fully crash" tests and will expand from there.

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='test', password='test')
        self.project = Project.objects.create()
        ProjectMembership.objects.create(project=self.project, user=self.user)
        self.issue = Issue.objects.create(project=self.project, **denormalized_issue_fields())
        self.event = create_event(self.project, self.issue)
        self.client.force_login(self.user)

    def test_event_download(self):
        response = self.client.get(f"/events/event/{self.event.pk}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_raw(self):
        response = self.client.get(f"/events/event/{self.event.pk}/raw/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertTrue("platform" in response.json())

    def test_event_plaintext(self):
        response = self.client.get(f"/events/event/{self.event.pk}/plain/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')


class TimeZoneTestCase(DjangoTestCase):
    """This class contains some tests that formalize my understanding of how Django works; they are not strictly tests
    of bugsink code.

    We put this in events/tests.py because that's a place where we use Django's TestCase, and we want to test in that
    context, as well as the one of Event models.
    """

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_with_default_conf(self):
        # check our default (test) conf
        self.assertEqual("Europe/Amsterdam", settings.TIME_ZONE)

        # save an event in the database; it will be saved in UTC (because that's what Django does)
        e = create_event()

        # we activate a timezone that is not UTC to ensure our tests run even when we're in a different timezone
        with timezone.override('America/Chicago'):
            self.assertEqual(datetime.timezone.utc, e.timestamp.tzinfo)

    def test_datetimes_are_in_utc_when_retrieved_from_the_database_no_matter_the_active_timezone_when_creating(self):
        with timezone.override('America/Chicago'):
            # save an event in the database; it will be saved in UTC (because that's what Django does); even when a
            # different timezone is active
            e = create_event()
            self.assertEqual(datetime.timezone.utc, e.timestamp.tzinfo)


class RetentionUtilsTestCase(RegularTestCase):
    def test_eviction_target(self):
        # over-target with low max: evict 5%
        self.assertEqual(5, eviction_target(100, 101))

        # over-target with high max: evict 500
        self.assertEqual(500, eviction_target(10_000, 10_001))
        self.assertEqual(500, eviction_target(100_000, 100_001))

        # adapted target, i.e. over target but by (much) more than 1: evict 500
        # (we chose this over the alternative of evicting all of the excess at once, because the latter could very well
        # lead to timeouts. this has the slightly surprising effect that eviction happens only in 500-event steps, and
        # because we don't trigger such steps unless new events come in, it could take a while to get back under target.
        # if this turns out to be a problem, we should just do that triggering ourselves rather than per-event).
        self.assertEqual(500, eviction_target(100, 10_001))

        # ridiciulously low max: evict 1
        self.assertEqual(1, eviction_target(6, 7))

        # Note that we have no special-casing for under-target (yet); not needed because should_evict (which does a
        # simple comparison) is always called first.
        # self.assertEqual(0, eviction_target(10_000, 9_999))


class RetentionTestCase(DjangoTestCase):

    def test_epoch_bounds_with_irrelevance_empty_project(self):
        project = Project.objects.create()
        current_timestamp = datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

        bounds = get_epoch_bounds_with_irrelevance(project, current_timestamp)

        self.assertEqual([((None, None), 0)], bounds)

    def test_epoch_bounds_with_irrelevance_single_current_event(self):
        project = Project.objects.create()
        current_timestamp = datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        create_event(project, timestamp=current_timestamp)

        bounds = get_epoch_bounds_with_irrelevance(project, current_timestamp)

        # all events are in the same (current) epoch, i.e. no explicit bounds, and no age-based irrelevance
        self.assertEqual([((None, None), 0)], bounds)

    def test_epoch_bounds_with_irrelevance_single_hour_old_event(self):
        project = Project.objects.create()
        current_timestamp = datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        create_event(project, timestamp=current_timestamp - datetime.timedelta(hours=1))

        bounds = get_epoch_bounds_with_irrelevance(project, current_timestamp)

        # with an observed event in the previous epoch, we get explicit bounds.
        self.assertEqual([
            ((455832, None), 0),  # present-till-future; no age-based irrelevance
            ((None, 455832), 1)  # all the past-till-present; age-based irrelevance 1
        ], bounds)

    def test_epoch_bounds_with_irrelevance_day_old_event(self):
        project = Project.objects.create()
        current_timestamp = datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        create_event(project, timestamp=current_timestamp - datetime.timedelta(days=1))

        bounds = get_epoch_bounds_with_irrelevance(project, current_timestamp)

        self.assertEqual([
            ((455832, None),   0),
            ((455829, 455832), 1),
            ((455817, 455829), 2),
            ((None,   455817), 3)],
            bounds)

    def test_retention_simple_case(self):
        # this test contains just the key bits of ingest/views.py such that we can test `evict_for_max_events`
        project_stored_event_count = 0
        digested_at = timezone.now()

        self.project = Project.objects.create(retention_max_event_count=5)
        self.issue = Issue.objects.create(project=self.project, **denormalized_issue_fields())

        for digest_order in range(1, 7):
            project_stored_event_count += 1  # +1 pre-create, as in the ingestion view
            create_event(self.project, self.issue, timestamp=digested_at)

            # in the real code calls to `evict_for_max_events` depend on `should_evict`; here we just test that both
            # work correctly for each step in the loop. (a more complete test, and there's no perfermance consideration)

            expected_should_evict = digest_order > 5

            evicted = evict_for_max_events(self.project, digested_at, project_stored_event_count)

            self.assertEqual(1 if expected_should_evict else 0, evicted.total)
            self.assertEqual(expected_should_evict, should_evict(self.project, digested_at, project_stored_event_count))

            project_stored_event_count -= evicted.total

    def test_retention_multiple_epochs(self):
        # this test contains just the key bits of ingest/views.py such that we can test `evict_for_max_events`;
        # at the same time, we diverge a bit from what would happen "in reality", such that we can make a test that's
        # both interesting (hits enough edge cases) and still understandable. In particular, we first load up on events
        # (over max) and then repeatedly evict (with small batch sizes) so we can see what's happening.
        project_stored_event_count = 0

        self.project = Project.objects.create(retention_max_event_count=999)
        self.issue = Issue.objects.create(project=self.project, **denormalized_issue_fields())

        current_timestamp = datetime.datetime(2022, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

        # the irrelevances here are chosen to be somewhat similar to reality as well as triggering interesting code
        # paths, in particular the "high irrelevances for recent epochs, non-consecutive" makes it so that you'll get
        # quite a few deletions where nothing happens (a branch that we also want to test).
        data = reversed(list(
            (i + 1, irrelevance, current_timestamp - datetime.timedelta(hours=i))
            for i, irrelevance in enumerate([0, 1, 2, 0, 1, 2, 0, 1, 4, 8])))

        for digest_order, irrelevance, digested_at in data:
            project_stored_event_count += 1  # +1 pre-create, as in the ingestion view
            event = create_event(self.project, self.issue, timestamp=digested_at)
            event.irrelevance_for_retention = irrelevance

            # totally unrealistic scenario of "everything is never_evict" is great for testing: it just means the
            # eviction framework is tested in "include_never_evict" mode which is "normal mode but more cases", i.e. it
            # tests the regular flow but also the special one.
            event.never_evict = True
            event.save()

        while project_stored_event_count > 1:
            # Just manually set the target a bit lower each time. We take batches of 2 because that's small enough to
            # have many batches, but big enough that a single batch will trigger multiple branches in our codebase.
            self.project.retention_max_event_count = project_stored_event_count - 2
            self.project.save()

            evicted = evict_for_max_events(self.project, current_timestamp, project_stored_event_count)
            self.assertEqual(2, evicted.total)

            project_stored_event_count -= evicted.total

    def test_filter_for_work(self):
        # this test is mostly to help clarify how filter_for_work actually works

        epoch_bounds = [((455832, None), 0), ((455829, 455832), 1), ((None, 455829), 2)]
        pairs = [(0, 0), (1, 2), (2, 2)]
        max_total_irrelevance = 3

        # only the oldest epoch has a total irrelevance exceeding the max; return only that:
        self.assertEqual([((None, 455829), 2)], list(filter_for_work(epoch_bounds, pairs, max_total_irrelevance)))


class AnnotateWithMetaTestCase(RegularTestCase):
    def test_annotate_with_meta(self):
        parsed_data = json.loads(EXAMPLE_META)

        exception_values = parsed_data["exception"]["values"]
        frames = exception_values[0]["stacktrace"]["frames"]
        meta_frames = parsed_data["_meta"]["exception"]["values"]["0"]["stacktrace"]["frames"]

        annotate_with_meta(exception_values, parsed_data["_meta"]["exception"]["values"])

        # length of the vars in a frame
        self.assertTrue(hasattr(frames[0]["vars"], "incomplete"))
        self.assertEqual(
            meta_frames["0"]["vars"][""]["len"] - len(frames[0]["vars"]),
            frames[0]["vars"].incomplete)

        # a var itself
        self.assertTrue(hasattr(frames[1]["vars"]["installed_apps"], "incomplete"))
        self.assertEqual(
            meta_frames["1"]["vars"]["installed_apps"][""]["len"] - len(frames[1]["vars"]["installed_apps"]),
            frames[1]["vars"]["installed_apps"].incomplete)

        # a var which is a list, containing a dict
        self.assertTrue(hasattr(frames[2]["vars"]["args"][1]["__builtins__"], "incomplete"))
        self.assertEqual(
            (meta_frames["2"]["vars"]["args"]["1"]["__builtins__"][""]["len"] -
             len(frames[2]["vars"]["args"][1]["__builtins__"])),
            frames[2]["vars"]["args"][1]["__builtins__"].incomplete)


EXAMPLE_META = r'''{
  "exception": {
    "values": [
      {
        "stacktrace": {
          "frames": [
            {
              "vars": {
                "os": "<module 'os' from '/usr/lib/python3.10/os.py'>"
              }
            },
            {
              "vars": {
                "self": "<django.apps.registry.Apps object at 0x7f65d4bdfeb0>",
                "installed_apps": [
                  "'projects'"
                ],
                "csrf_token": "[Filtered]"
              }
            },
            {
              "vars": {
                "f": "<built-in function exec>",
                "args": [
                  "<code object <module> at 0x7f65d33e92c0, file \"...\", line 1>",
                  {
                    "__name__": "'releases.models'",
                    "__builtins__": {
                      "any": "<built-in function any>"
                    }
                  }
                ]
              }
            }
          ]
        }
      }
    ]
  },
  "_meta": {
    "exception": {
      "values": {
        "0": {
          "stacktrace": {
            "frames": {
              "0": {
                "vars": {
                  "": {
                    "len": 12
                  }
                }
              },
              "1": {
                "vars": {
                  "installed_apps": {
                    "": {
                      "len": 16
                    }
                  },
                  "csrf_token": {
                    "": {
                      "rem": [
                        [
                          "!config",
                          "s"
                        ]
                      ]
                    }
                  }
                }
              },
              "2": {
                "vars": {
                  "args": {
                    "1": {
                      "__builtins__": {
                        "": {
                          "len": 155
                        }
                      },
                      "": {
                        "len": 13
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}'''  # extracted from a real event; limited to the parts that are needed for annotate_with_meta
