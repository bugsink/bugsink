import json
from django.test import TestCase as DjangoTestCase
from datetime import timedelta

from projects.models import Project

from django.test import TestCase
from django.utils import timezone

from issues.models import TurningPoint, TurningPointKind
from issues.factories import get_or_create_issue

from .models import Release, ordered_releases, RE_PACKAGE_VERSION, create_release_if_needed


class ReleaseTestCase(DjangoTestCase):

    def test_create_and_order(self):
        project = Project.objects.create(name="Test Project")

        r0 = Release.objects.create(project=project, version="e80f98923f7426a8087009f4c629d25a35565a6a")
        self.assertFalse(r0.is_semver)
        self.assertEqual(0, r0.sort_epoch)

        # still using hash; stay at epoch 0
        # the timedelta has 2 purposes:
        # * when the tests are very fast, it ensures that r0 and r1 are not created at the same time (as it would be in
        #   real usage too)
        # * it ensures that dates are ignored when comparing r1 and r2 (r2 has a smaller date than r1, but comes later)
        r1 = Release.objects.create(
            project=project,
            version="2a678dbbbecd2978ccaa76c326a0fb2e70073582",
            date_released=r0.date_released + timedelta(seconds=10),
        )
        self.assertFalse(r1.is_semver)
        self.assertEqual(0, r1.sort_epoch)

        # switch to semver, epoch 1
        r2 = Release.objects.create(project=project, version="1.0.0")
        self.assertTrue(r2.is_semver)
        self.assertEqual(1, r2.sort_epoch)

        # stick with semver, but use a lower version
        r3 = Release.objects.create(project=project, version="0.1.0")
        self.assertTrue(r3.is_semver)
        self.assertEqual(1, r3.sort_epoch)

        # put in package name; this is basically ignored for ordering purposes
        r4 = Release.objects.create(project=project, version="package@2.0.0")
        self.assertTrue(r4.is_semver)

        self.assertEqual(ordered_releases(), [r0, r1, r3, r2, r4])

    def test_re_package_version(self):
        self.assertEqual({"package": None, "version": "foo"}, RE_PACKAGE_VERSION.match("foo").groupdict())

        self.assertEqual({"package": None, "version": "1.2.3"}, RE_PACKAGE_VERSION.match("1.2.3").groupdict())

        self.assertEqual(
            {"package": "mypackage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("mypackage@1.2.3").groupdict())

        self.assertEqual(
            {"package": "@mypackage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("@mypackage@1.2.3").groupdict())

        # Sentry (as of late 2023) only allows an at-sign at the beginning of a package name, not anywhere else. I can't
        # find any documentation or git-logs for why, so this is not replicated here.
        self.assertEqual(
            {"package": "@mypac@kage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("@mypac@kage@1.2.3").groupdict())


class CreateReleaseIfNeededTests(TestCase):
    def setUp(self):
        self.timestamp0 = timezone.now()
        self.timestamp1 = self.timestamp0 + timedelta(seconds=5)
        self.timestamp2 = self.timestamp1 + timedelta(seconds=5)

    def test_empty_version_creates_release_without_side_effects(self):
        project = Project.objects.create()

        release, created = create_release_if_needed(project, "", self.timestamp0)
        self.assertTrue(created)
        self.assertEqual(release.version, "")
        self.assertEqual(release.date_released, self.timestamp0)

        project.refresh_from_db()
        self.assertFalse(getattr(project, "has_releases", False))
        self.assertEqual(TurningPoint.objects.count(), 0)

    def test_turning_point_metadata_contains_actual_release(self):
        project = Project.objects.create()
        issue, _ = get_or_create_issue(project=project)
        issue.is_resolved_by_next_release = True
        issue.save()

        create_release_if_needed(project, "1.2.3", self.timestamp0)
        turning_point = TurningPoint.objects.filter(kind=TurningPointKind.NEXT_MATERIALIZED, project=project).first()
        self.assertIsNotNone(turning_point)
        self.assertEqual(json.loads(turning_point.metadata).get("actual_release"), "1.2.3")

    def test_idempotent_when_release_exists(self):
        project = Project.objects.create()

        create_release_if_needed(project, "2.0.0", self.timestamp0)
        turning_point_count_before = TurningPoint.objects.count()
        has_releases_before = getattr(project, "has_releases", False)

        _, created = create_release_if_needed(project, "2.0.0", self.timestamp1)
        self.assertFalse(created)

        self.assertEqual(TurningPoint.objects.count(), turning_point_count_before)
        project.refresh_from_db()
        self.assertEqual(getattr(project, "has_releases", False), has_releases_before)

    def test_next_release_materialization_transforms_issue(self):
        project = Project.objects.create()
        issue, _ = get_or_create_issue(project=project)
        issue.is_resolved = True
        issue.is_resolved_by_next_release = True
        issue.fixed_at = ""
        issue.save()

        create_release_if_needed(project, "1.0.0", self.timestamp0)

        issue.refresh_from_db()
        self.assertTrue(issue.is_resolved)
        self.assertFalse(issue.is_resolved_by_next_release)
        self.assertEqual(issue.fixed_at, "1.0.0\n")

        self.assertEqual(
            TurningPoint.objects.filter(
                project=project, issue=issue, kind=TurningPointKind.NEXT_MATERIALIZED
            ).count(),
            1,
        )
