from django.test import TestCase
from datetime import timedelta

from .models import Release, ordered_releases


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

        self.assertEquals(ordered_releases(), [r0, r1, r3, r2])
