import uuid

from semver.version import Version

from django.db import models
from django.utils import timezone


def is_valid_semver(version):
    try:
        Version.parse(version)
        return True
    except ValueError:
        return False


def sort_key(release):
    return (
        release.sort_epoch,
        Version.parse(release.version) if release.is_semver else release.date_released
    )


def ordered_releases(*filter_args, **filter_kwargs):
    """..."""
    releases = Release.objects.filter(*filter_args, **filter_kwargs)

    return sorted(releases, key=sort_key)


class Release(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    version = models.CharField(max_length=255, null=False, blank=False)

    date_released = models.DateTimeField(default=timezone.now)

    is_semver = models.BooleanField()
    sort_epoch = models.IntegerField()

    def save(self, *args, **kwargs):
        if self.is_semver is None:
            self.is_semver = is_valid_semver(self.version)

            # whether doing this epoch setting inline on-creation is a smart idea... will become clear soon enough.
            any_release_from_last_epoch = Release.filter(project=self.project).objects.order_by("sort_epoch").last()
            if any_release_from_last_epoch is None:
                self.sort_epoch = 0
            elif self.is_semver == any_release_from_last_epoch.is_semver:
                self.sort_epoch = any_release_from_last_epoch.sort_epoch
            else:
                self.sort_epoch = any_release_from_last_epoch.sort_epoch + 1

        super(Release, self).save(*args, **kwargs)

    class Meta:
        unique_together = ("project", "version")
