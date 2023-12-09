import re
import uuid

from semver.version import Version

from django.db import models
from django.utils import timezone


RE_PACKAGE_VERSION = re.compile('((?P<package>.*)[@])?(?P<version>.*)')


def is_valid_semver(full_version):
    try:
        version = RE_PACKAGE_VERSION.match(full_version).groupdict()["version"]
        Version.parse(version)
        return True
    except ValueError:
        return False


def sort_key(release):
    return (
        release.sort_epoch,
        Version.parse(release.semver) if release.is_semver else release.date_released
    )


def ordered_releases(*filter_args, **filter_kwargs):
    """..."""
    releases = Release.objects.filter(*filter_args, **filter_kwargs)

    return sorted(releases, key=sort_key)


class Release(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # sentry does releases per-org; we don't follow that example. our belief is basically: [1] in reality releases are
    # per software package and a software package is basically a bugsink project and [2] any cross-project-per-org
    # analysis you might do is more likely to be in the realm of "transactions", something we don't want to support.
    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # full version as provided by either implicit (per-event) or explicit (some API) means, including package name
    version = models.CharField(max_length=255, null=False, blank=False)

    date_released = models.DateTimeField(default=timezone.now)

    semver = models.CharField(max_length=255, null=False, editable=False)
    is_semver = models.BooleanField(editable=False)
    sort_epoch = models.IntegerField(editable=False)

    def save(self, *args, **kwargs):
        if self.is_semver is None:
            self.is_semver = is_valid_semver(self.version)
            if self.is_semver:
                self.semver = RE_PACKAGE_VERSION.match(self.version)["version"]

            # whether doing this epoch setting inline on-creation is a smart idea... will become clear soon enough.
            any_release_from_last_epoch = Release.objects.filter(project=self.project).order_by("sort_epoch").last()
            if any_release_from_last_epoch is None:
                self.sort_epoch = 0
            elif self.is_semver == any_release_from_last_epoch.is_semver:
                self.sort_epoch = any_release_from_last_epoch.sort_epoch
            else:
                self.sort_epoch = any_release_from_last_epoch.sort_epoch + 1

        super(Release, self).save(*args, **kwargs)

    class Meta:
        unique_together = ("project", "version")
