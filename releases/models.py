import json
import re
import uuid

from semver.version import Version

from django.db import models
from django.utils import timezone
from django.db.models.functions import Concat
from django.db.models import Value

from issues.models import Issue, TurningPoint, TurningPointKind


RE_PACKAGE_VERSION = re.compile('((?P<package>.*)[@])?(?P<version>.*)')


def is_valid_semver(full_version):
    try:
        version = RE_PACKAGE_VERSION.match(full_version).groupdict()["version"]
        Version.parse(version)
        return True
    except ValueError:
        return False


def release_sort_key(release):
    return (
        release.sort_epoch,
        Version.parse(release.semver) if release.is_semver else release.date_released
    )


def ordered_releases(*filter_args, **filter_kwargs):
    """Sorting Release objects in code (as opposed to in-DB) to facilitate semver-based sorting when applicable"""
    releases = Release.objects.filter(*filter_args, **filter_kwargs)

    return sorted(releases, key=release_sort_key)


class Release(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # sentry does releases per-org; we don't follow that example. our belief is basically: [1] in reality releases are
    # per software package and a software package is basically a bugsink project and [2] any cross-project-per-org
    # analysis you might do is more likely to be in the realm of "transactions", something we don't want to support.
    project = models.ForeignKey(
        "projects.Project", blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    # full version as provided by either implicit (per-event) or explicit (some API) means, including package name
    # max_length matches Even.release (which is deduced from Sentry)
    version = models.CharField(max_length=250, null=False, blank=False)

    date_released = models.DateTimeField(default=timezone.now)

    semver = models.CharField(max_length=255, null=False, editable=False)
    is_semver = models.BooleanField(editable=False)

    # sort_epoch is a way to ensure that we can sort releases alternatingly by date and by semver. The idea is that
    # whenever we switch from one to the other, we increment the epoch. This way, we can sort releases by epoch first
    # and then by date or semver. i.e. when transitioning between version schemes, ordering will "Just Work".
    # The typical scenario involves a straightforward shift from a state of "being too lazy to set up and merely using
    # hashes" to adopting semver.
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

        indexes = [
            models.Index(fields=["sort_epoch"]),
        ]

    def get_short_version(self):
        if self.version == "":
            # the reason for this little hack is to have something show up in the UI for this case. I 'assume' (mother
            # of all ...) that in most reasonable cases we actually don't show releases if there's an empty release
            # (i.e. for the single empty release we really shouldn't, because then project.has_releases should be false)
            # but I've seen at least one case where you still have to show something even for the empty release: when
            # switching back to "no release". (that's why I say "most reasonable cases"). (observed in testing, because
            # test-events generally wildly vary in the release info they carry).
            return "«no version»"
        if self.is_semver:
            return self.version
        return self.version[:12]


def create_release_if_needed(project, version, event, issue=None):
    if version is None:
        # because `create_release_if_needed` is called with Issue.release (non-nullable), the below "won't happen"
        raise ValueError('The None-like version must be the empty string')

    # NOTE: we even create a Release for the empty release here; we need the associated info (date_released) if a
    # real release is ever created later.

    version = sanitize_version(version)

    release, release_created = Release.objects.get_or_create(project=project, version=version)
    if release_created and version != "":
        if not project.has_releases:
            project.has_releases = True
            project.save()

        if release == project.get_latest_release():
            resolved_by_next_qs = Issue.objects.filter(project=project, is_resolved_by_next_release=True)

            # NOTE: once we introduce an explicit way of creating releases (not event-based) we can not rely on a
            # triggering event anymore for our timestamp.

            TurningPoint.objects.bulk_create([TurningPoint(
                    issue=issue, kind=TurningPointKind.NEXT_MATERIALIZED, triggering_event=event,
                    metadata=json.dumps({"actual_release": release.version}), timestamp=event.ingested_at)
                for issue in resolved_by_next_qs
            ])
            event.never_evict = True  # .save() will be called by the caller of this function

            resolved_by_next_qs.update(
                fixed_at=Concat("fixed_at", Value(release.version + "\n")),
                is_resolved_by_next_release=False,
                )

            if issue is not None and issue.is_resolved_by_next_release:
                # a bit of a hack: if we have an in-memory issue, we must update it as well.
                issue.fixed_at = issue.fixed_at + release.version + "\n"
                issue.is_resolved_by_next_release = False

    return release


def sanitize_version(version):
    """
    Implements the folllowing restrictions are from the Sentry documentation:

    > There are a few restrictions -- the release name cannot:
    >
    > - contain newlines, tabulator characters, forward slashes(/), or back slashes(\\)
    > - be (in their entirety) period (.), double period (..), or space ( )
    > - exceed 200 characters

    It does so as sanitize-dont-raise, i.e. it will return a sanitized version of the input string, but will not raise
    an exception if the input string is invalid. Reason: we care about having valid data (and we rely e.g. on the lack
    of newlines for our parsing), but we never want an invalid input to lead to discarded events. And there's no one
    to 'read' a rejected event and fix it.
    """

    step_1 = version.replace("\n", "").replace("\t", "").replace("/", "").replace("\\", "")
    step_2 = "sanitized" if step_1 in (".", "..", " ") else step_1
    step_3 = step_2[:200]
    return step_3
