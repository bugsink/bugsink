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
from .retention import eviction_target, should_evict, evict_for_max_events
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
    # test-second TestCase for retention/eviction. "At least have something that touches the main parts of the code to
    # avoid the most obvious kinds of breakages". Not a full test of all features/code paths (yet).

    def test_retention(self):
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

            self.assertEqual(1 if expected_should_evict else 0, evicted)
            self.assertEqual(expected_should_evict, should_evict(self.project, digested_at, project_stored_event_count))

            project_stored_event_count -= evicted


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
                ]
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
