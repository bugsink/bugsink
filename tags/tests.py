from django.test import TestCase as DjangoTestCase

from tags.models import store_tags
from projects.models import Project
from issues.factories import get_or_create_issue
from events.factories import create_event


class TagsTestCase(DjangoTestCase):
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
