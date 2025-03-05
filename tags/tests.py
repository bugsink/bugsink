from unittest import TestCase as RegularTestCase
from django.test import TestCase as DjangoTestCase

from projects.models import Project
from issues.factories import get_or_create_issue
from events.factories import create_event

from .models import store_tags
from .utils import deduce_tags


class DeduceTagsTestCase(RegularTestCase):

    def test_deduce_tags(self):
        self.assertEqual(deduce_tags({}), {})
        self.assertEqual(deduce_tags({"tags": {"foo": "bar"}}), {"foo": "bar"})

        # finally, a more complex example (more or less real-world)
        event_data = {
            "server_name": "server",
            "release": "1.0",
            "environment": "prod",
            "transaction": "main",
            "contexts": {
                "trace": {
                    "trace_id": "1f2d3e4f5a6b5c8df9e0a1b2c3d4e5f",
                    "span_id": "9a8b7c6d5e4f3a2c",
                },
                "browser": {
                    "name": "Chrome",
                    "version": "88",
                },
                "os": {
                    "name": "Windows",
                    "version": "10",
                },
            },
        }
        self.assertEqual(deduce_tags(event_data), {
            "server_name": "server",
            "release": "1.0",
            "environment": "prod",
            "transaction": "main",
            "trace": "1f2d3e4f5a6b5c8df9e0a1b2c3d4e5f",
            "trace.span": "9a8b7c6d5e4f3a2c",
            "trace.ctx": "1f2d3e4f5a6b5c8df9e0a1b2c3d4e5f.9a8b7c6d5e4f3a2c",
            "browser.name": "Chrome",
            "browser.version": "88",
            "browser": "Chrome 88",
            "os.name": "Windows",
            "os.version": "10",
            "os": "Windows 10",
        })


class StoreTagsTestCase(DjangoTestCase):
    # NOTE: I do quite a few assertNumQueries() in the below; super-brittle and opaque, of course. But at least the
    # brittle part is quick to fix (a single number) and provides a canary for performance regressions.

    def setUp(self):
        self.project = Project.objects.create(name="Test Project")
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, issue=self.issue)

    def test_store_0_tags(self):
        with self.assertNumQueries(0):
            store_tags(self.event, self.issue, {})

        self.assertEqual(self.event.tags.count(), 0)

    def test_store_1_tags(self):
        with self.assertNumQueries(7):
            store_tags(self.event, self.issue, {"foo": "bar"})

        self.assertEqual(self.event.tags.count(), 1)
        self.assertEqual(self.issue.tags.count(), 1)

        self.assertEqual(self.event.tags.first().value.value, "bar")

        self.assertEqual(self.issue.tags.first().count, 1)
        self.assertEqual(self.issue.tags.first().value.key.key, "foo")

    def test_store_5_tags(self):
        with self.assertNumQueries(7):
            store_tags(self.event, self.issue, {f"k-{i}": f"v-{i}" for i in range(5)})

        self.assertEqual(self.event.tags.count(), 5)
        self.assertEqual(self.issue.tags.count(), 5)

        self.assertEqual({"k-0", "k-1", "k-2", "k-3", "k-4"}, {tag.value.key.key for tag in self.event.tags.all()})
        self.assertEqual({"v-0", "v-1", "v-2", "v-3", "v-4"}, {tag.value.value for tag in self.event.tags.all()})

    def test_store_single_tag_twice_on_issue(self):
        store_tags(self.event, self.issue, {"foo": "bar"})
        store_tags(create_event(self.project, self.issue), self.issue, {"foo": "bar"})

        self.assertEqual(self.issue.tags.first().count, 2)
        self.assertEqual(self.issue.tags.first().value.key.key, "foo")
