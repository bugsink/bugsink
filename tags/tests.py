from unittest import TestCase as RegularTestCase
from django.test import TestCase as DjangoTestCase
from django.conf import settings

from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project
from issues.factories import get_or_create_issue, denormalized_issue_fields
from events.factories import create_event, create_event_data
from issues.models import Issue

from .models import store_tags, EventTag, IssueTag, TagValue, digest_tags
from .utils import deduce_tags
from .search import search_events, search_issues, parse_query, search_events_optimized
from .tasks import vacuum_eventless_issuetags


class DeduceTagsTestCase(RegularTestCase):

    def test_deduce_tags(self):
        self.assertEqual(deduce_tags({}), {})
        self.assertEqual(deduce_tags({"tags": {"foo": "bar"}}), {"foo": "bar"})

        event_data = {
            "server_name": "server",
            "release": "1.0",
            "environment": "prod",
            "exception": {
                "values": [{
                    "mechanism": {
                        "type": "exception",
                        "handled": False,
                    },
                }],
            },
            "user": {
                "id": "12345",
                "username": "johndoe",
                "email": "john@doe.org",
                "ip_address": "123.123.123.123",
            },
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
            "handled": "false",
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
            "user": "12345",
            "user.id": "12345",
            "user.username": "johndoe",
            "user.email": "john@doe.org",
            "user.ip_address": "123.123.123.123",
        })


class StoreTagsTestCase(DjangoTestCase):
    # NOTE: I do quite a few assertNumQueries() in the below; super-brittle and opaque, of course. But at least the
    # brittle part is quick to fix (a single number) and provides a canary for performance regressions.

    def setUp(self):
        self.project = Project.objects.create(name="Test Project")
        self.issue, _ = get_or_create_issue(self.project)
        self.event = create_event(self.project, issue=self.issue)
        # correct for mysql's inability to shave 2 queries off
        self.correct_for_mysql = 2 if 'mysql' in settings.DATABASES['default']['ENGINE'] else 0

    def test_store_0_tags(self):
        with self.assertNumQueries(0):
            store_tags(self.event, self.issue, {})

        self.assertEqual(self.event.tags.count(), 0)

    def test_store_1_tags(self):
        with self.assertNumQueries(5 + self.correct_for_mysql):
            store_tags(self.event, self.issue, {"foo": "bar"})

        self.assertEqual(self.event.tags.count(), 1)
        self.assertEqual(self.issue.tags.count(), 1)

        self.assertEqual(self.event.tags.first().value.value, "bar")
        self.assertEqual(self.event.tags.first().issue, self.issue)

        self.assertEqual(self.issue.tags.first().count, 1)
        self.assertEqual(self.issue.tags.first().value.key.key, "foo")

    def test_store_5_tags(self):
        with self.assertNumQueries(5 + self.correct_for_mysql):
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

    def test_store_same_tag_on_two_issues_creates_two_issuetags(self):
        store_tags(self.event, self.issue, {"foo": "bar"})

        other_issue, _ = get_or_create_issue(self.project, event_data=create_event_data("other_issue"))
        other_event = create_event(self.project, issue=other_issue)
        store_tags(other_event, other_issue, {"foo": "bar"})

        self.assertEqual(IssueTag.objects.count(), 2)
        self.assertEqual(2, IssueTag.objects.filter(value__key__key="foo").count())

    def test_store_many_tags(self):
        # observed: a non-batched implementation of store_tags() would crash (e.g. in sqlite: Expression tree is too
        # large (maximum depth 1000)); if the below doesn't crash, we've got a batched implementation that works
        event = create_event(self.project, issue=self.issue)
        store_tags(event, self.issue, {f"key-{i}": f"value-{i}" for i in range(512)})
        self.assertEqual(IssueTag.objects.filter(issue=self.issue).count(), 512)


class DigestTagsTestCase(DjangoTestCase):
    def test_auto_ip_address(self):
        project = Project.objects.create(name="Test Project")
        issue, _ = get_or_create_issue(project)
        event = create_event(project, issue=issue)

        event_data = {
            "user": {
                "ip_address": "{{auto}}",
            },
        }
        event.remote_addr = "123.123.123.123"
        event.save()
        digest_tags(event_data, event, issue)

        # twice because "user" and "user.ip_address"
        self.assertEqual(["123.123.123.123", "123.123.123.123"], [e.value.value for e in event.get_tags])

    def test_auto_ip_address_when_not_available(self):
        # could be non-available because of proxy misconfig or other reasons, in any case it should not break anything:
        # Event.remote_addr is nullable so downstream code should be able to handle None
        project = Project.objects.create(name="Test Project")
        issue, _ = get_or_create_issue(project)
        event = create_event(project, issue=issue)

        event_data = {
            "user": {
                "ip_address": "{{auto}}",
            },
        }
        event.remote_addr = None
        event.save()
        digest_tags(event_data, event, issue)

        self.assertEqual([], [e.value.value for e in event.get_tags])


class SearchParserTestCase(RegularTestCase):

    def test_parser(self):
        # we don't actually do the below, empty queries are never parsed
        # self.assertEqual(({}, ""), parse_query(""))

        self.assertEqual(({}, "FindableException"), parse_query("FindableException"))
        self.assertEqual(({}, "findable value"), parse_query("findable value"))

        self.assertEqual(({"key": "value"}, ""),  parse_query("key:value"))
        self.assertEqual(
            ({"key": "value", "anotherkey": "anothervalue"}, ""),
            parse_query("key:value anotherkey:anothervalue"))

        self.assertEqual(
            ({"keys.may.have.dots": "values.may.have.dots.too"}, ""),
            parse_query("keys.may.have.dots:values.may.have.dots.too"))

        self.assertEqual(
            ({"key": "value"}, "some text goes here"),
            parse_query("key:value some text goes here"))

        self.assertEqual(
            ({}, "text  with  spaces  everywhere"),
            parse_query("text  with  spaces  everywhere"))

        self.assertEqual(
            ({}, "key: preceded by space"),
            parse_query("key: preceded by space"))

        self.assertEqual(
            ({"key": "quoted value"}, ""),
            parse_query('key:"quoted value"'))

        self.assertEqual(
            ({"key": "quoted value"}, "and further text"),
            parse_query('key:"quoted value" and further text'))

        # This is the kind of test that just documents "what is" rather than "what I believe is right". The weirdness
        # here is mostly the double space "on  both" which is the result of just cutting out the key:value bits. But...
        # I'm not invested in getting this more precise (yet), because this whole case is a bit weird. I'd much rather
        # point people in the direction of "put k:v at the beginning, and any free text at the end" (which is something
        # we could even validate on at some later point).
        self.assertEqual(
            ({"key": "value"}, "text on  both sides"),
            parse_query("text on key:value both sides"))


class SearchTestCase(DjangoTestCase):
    """'Integration'-test; assuming Tags are stored correctly in the DB, can we search for them?"""

    def setUp(self):
        self.project = Project.objects.create(name="Test Project")

        # we create a single issue to group all the events under; this is not what would happen in the real world
        # scenario (in which there would be some relation between the tags of issues and events), but it allows us to
        # test event_search more easily (if each event is tied to a different issue, searching for tags is meaningless,
        # since you always search within the context of an issue).
        self.global_issue, _ = get_or_create_issue(project=self.project, event_data=create_event_data("global"))

        issue_with_tags_and_text, _ = get_or_create_issue(project=self.project, event_data=create_event_data("tag_txt"))
        event_with_tags_and_text = create_event(self.project, issue=self.global_issue)

        issue_with_tags_no_text, _ = get_or_create_issue(project=self.project, event_data=create_event_data("no_text"))
        event_with_tags_no_text = create_event(self.project, issue=self.global_issue)

        store_tags(event_with_tags_and_text, issue_with_tags_and_text, {f"k-{i}": f"v-{i}" for i in range(5)})
        store_tags(event_with_tags_no_text, issue_with_tags_no_text, {f"k-{i}": f"v-{i}" for i in range(5)})
        # fix the EventTag objects' issue, which is broken per the non-real-world setup (see above)
        EventTag.objects.all().update(issue=self.global_issue)

        issue_without_tags, _ = get_or_create_issue(project=self.project, event_data=create_event_data("no_tags"))
        event_without_tags = create_event(self.project, issue=self.global_issue)

        for obj in [issue_with_tags_and_text, event_with_tags_and_text, issue_without_tags, event_without_tags]:
            obj.calculated_type = "FindableException"
            obj.calculated_value = "findable value"
            obj.save()

        get_or_create_issue(project=self.project, event_data=create_event_data("no_text"))
        create_event(self.project, issue=self.global_issue)

    def _test_search(self, search_x):
        # no query: all results
        self.assertEqual(search_x("").count(), search_x("").model.objects.count())

        # in the above, we create 2 items with tags
        self.assertEqual(search_x("k-0:v-0").count(), 2)

        # an "AND" query should yield the same 2
        self.assertEqual(search_x("k-0:v-0 k-1:v-1").count(), 2)

        # non-matching tag: no results
        self.assertEqual(search_x("k-0:nosuchthing").count(), 0)
        self.assertEqual(search_x("k-0:nosuchthing k-1:v-1").count(), 0)

        # findable-by-text: 2 such items
        self.assertEqual(search_x("findable value").count(), 2)
        self.assertEqual(search_x("FindableException").count(), 2)

        # non-matching text: no results
        self.assertEqual(search_x("nosuchthing").count(), 0)
        self.assertEqual(search_x("k-0:v-0 nosuchthing").count(), 0)

        # findable-by-text, tagged: 1 such item
        self.assertEqual(search_x("findable value k-0:v-0").count(), 1)

    def test_search_events(self):
        self._test_search(lambda query: search_events(self.project, self.global_issue, query))

    def test_search_events_optimized(self):
        self._test_search(lambda query: search_events_optimized(self.project, self.global_issue, query))

    def test_search_events_wrong_issue(self):
        issue_without_events = Issue.objects.create(project=self.project, **denormalized_issue_fields())

        search_x = lambda query: search_events(self.project, issue_without_events, query)

        # those lines from _test_search() that had non-zero results are now expected to have 0 results
        self.assertEqual(search_x("").count(), 0)
        self.assertEqual(search_x("k-0:v-0").count(), 0)
        self.assertEqual(search_x("findable value").count(), 0)
        self.assertEqual(search_x("FindableException").count(), 0)
        self.assertEqual(search_x("findable value k-0:v-0").count(), 0)

    def test_search_issues(self):
        self._test_search(lambda query: search_issues(self.project, Issue.objects.all(), query))


class VacuumEventlessIssueTagsTestCase(TransactionTestCase):
    # Note: this test depends on EAGER mode in both the setup (delete_derred to trigger cascading deletes) and the
    # testing of the thing under test (vacuum_eventless_issuetags).

    def setUp(self):
        self.project = Project.objects.create(name="T")
        self.issue, _ = get_or_create_issue(self.project)

    def test_no_eventtags_means_vacuum(self):
        event = create_event(self.project, issue=self.issue)
        store_tags(event, self.issue, {"foo": "bar"})
        event.delete_deferred()

        self.assertEqual(IssueTag.objects.count(), 1)
        vacuum_eventless_issuetags()
        # in the above we deleted EventTag; implies 0 after-vacuum
        self.assertEqual(IssueTag.objects.count(), 0)

    def test_one_eventtag_preserves_issuetag(self):
        event = create_event(self.project, issue=self.issue)
        store_tags(event, self.issue, {"foo": "bar"})

        self.assertEqual(IssueTag.objects.count(), 1)
        vacuum_eventless_issuetags()
        # in the above we did not delete EventTag; implies 1 after-vacuum
        self.assertEqual(IssueTag.objects.count(), 1)

    def test_other_event_same_tag_same_issue_preserves(self):
        event1 = create_event(self.project, issue=self.issue)
        event2 = create_event(self.project, issue=self.issue)
        store_tags(event1, self.issue, {"foo": "bar"})
        store_tags(event2, self.issue, {"foo": "bar"})
        event1.delete_deferred()

        self.assertEqual(IssueTag.objects.count(), 1)
        vacuum_eventless_issuetags()
        # we deleted the EventTag for event1, but since event2 has the same tag, it should be preserved on the Issue
        self.assertEqual(IssueTag.objects.count(), 1)

    def test_other_event_same_tag_other_issue_does_not_preserve(self):
        event1 = create_event(self.project, issue=self.issue)
        store_tags(event1, self.issue, {"foo": "bar"})

        other_issue, _ = get_or_create_issue(self.project, event_data=create_event_data("other_issue"))
        event2 = create_event(self.project, issue=other_issue)
        store_tags(event2, other_issue, {"foo": "bar"})

        event1.delete_deferred()

        self.assertEqual(IssueTag.objects.filter(issue=self.issue).count(), 1)
        vacuum_eventless_issuetags()
        self.assertEqual(IssueTag.objects.filter(issue=self.issue).count(), 0)

    def test_many_tags_spanning_chunks(self):
        event = create_event(self.project, issue=self.issue)
        store_tags(event, self.issue, {f"key-{i}": f"value-{i}" for i in range(2048 + 1)})  # bigger than BATCH_SIZE

        # check setup: all issue tags are there
        self.assertEqual(IssueTag.objects.filter(issue=self.issue).count(), 2048 + 1)

        event.delete_deferred()
        vacuum_eventless_issuetags()

        # all tags should be gone after vacuum
        self.assertEqual(IssueTag.objects.filter(issue=self.issue).count(), 0)

    def test_tagvalue_is_pruned(self):
        event = create_event(self.project, issue=self.issue)
        store_tags(event, self.issue, {"foo": "bar"})
        event.delete_deferred()

        vacuum_eventless_issuetags()
        self.assertEqual(TagValue.objects.all().count(), 0)
