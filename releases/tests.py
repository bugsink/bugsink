from django.test import TestCase
from datetime import timedelta

from .models import Release, ordered_releases, RE_PACKAGE_VERSION


class ReleaseTestCase(TestCase):

    def test_create_and_order(self):
        r0 = Release.objects.create(version="e80f98923f7426a8087009f4c629d25a35565a6a")
        self.assertFalse(r0.is_semver)
        self.assertEquals(0, r0.sort_epoch)

        # still using hash; stay at epoch 0
        # the timedelta avoids tests breaking when fast & checks dates are ignored when comparing against semver
        r1 = Release.objects.create(
            version="2a678dbbbecd2978ccaa76c326a0fb2e70073582",
            date_released=r0.date_released + timedelta(seconds=10),
        )
        self.assertFalse(r1.is_semver)
        self.assertEquals(0, r1.sort_epoch)

        # switch to semver, epoch 1
        r2 = Release.objects.create(version="1.0.0")
        self.assertTrue(r2.is_semver)
        self.assertEquals(1, r2.sort_epoch)

        # stick with semver, but use a lower version
        r3 = Release.objects.create(version="0.1.0")
        self.assertTrue(r3.is_semver)
        self.assertEquals(1, r3.sort_epoch)

        # put in package name; this is basically ignored for ordering purposes
        r4 = Release.objects.create(version="package@2.0.0")
        self.assertTrue(r4.is_semver)

        self.assertEquals(ordered_releases(), [r0, r1, r3, r2, r4])

    def test_re_package_version(self):
        self.assertEquals({"package": None, "version": "foo"}, RE_PACKAGE_VERSION.match("foo").groupdict())

        self.assertEquals({"package": None, "version": "1.2.3"}, RE_PACKAGE_VERSION.match("1.2.3").groupdict())

        self.assertEquals(
            {"package": "mypackage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("mypackage@1.2.3").groupdict())

        self.assertEquals(
            {"package": "@mypackage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("@mypackage@1.2.3").groupdict())

        # Sentry (as of late 2023) only allows an at-sign at the beginning of a package name, not anywhere else. I can't
        # find any documentation or git-logs for why, so this is not replicated here.
        self.assertEquals(
            {"package": "@mypac@kage", "version": "1.2.3"},
            RE_PACKAGE_VERSION.match("@mypac@kage@1.2.3").groupdict())