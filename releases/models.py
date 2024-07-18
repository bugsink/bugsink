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
    """Python-based sorting of Release objects (to facilitate semver-based sorting when applicable)"""
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

    def get_short_version(self):
        if self.is_semver:
            return self.version
        return self.version[:12]


def create_release_if_needed(project, version, event):
    if version is None:
        # it is the empty string in practice because we pull this from Issue.release, which is non-nullable
        raise ValueError('The None-like version must be the empty string')

    # NOTE: we even create a Release for the empty release here; we need the associated info (date_released) if a
    # real release is ever created later.

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

    return release


# Some thoughts that should go into a proper doc-like location later:
#
# 1. The folllowing restrictions are not (yet?) replicated from Sentry:
#
# There are a few restrictions -- the release name cannot:
#
# - contain newlines, tabulator characters, forward slashes(/), or back slashes(\\)
# - be (in their entirety) period (.), double period (..), or space ( )
# - exceed 200 characters
#
# 2. Sentry has the following "recommendations":
#
# > - for mobile devices use `package-name@version-number` or `package-name@version-number+build-number`. **Do not** use
#     `VERSION_NUMBER (BUILD_NUMBER)` as the parenthesis are used for display purposes (foo@1.0+2 becomes 1.0 (2)), so
#     invoking them will cause an error.  > - if you use a DVCS we recommend using the identifying hash (eg: the commit
#     SHA, `da39a3ee5e6b4b0d3255bfef95601890afd80709`). You can let sentry-cli automatically determine this hash for
#     supported version control systems with `sentry-cli releases propose-version`.
# > - if you tag releases we recommend using the release tag prefixed with a product or package name (for example,
#     `my-project-name@2.3.12`).
#
# We'd word that slightly differently:
#
# * We strongly recommend using semver† for your versions; if you do, releases will be ordered as you'd expect and
#   humans will find it much easier to pronounce/reason about versions.
# * Any non-semver versions will be ordered by date. The typical use-case would be commit-hashes, but since the ordering
#   is by date and there is no special handling for commit hashes it really doesn't matter.
# * Any characters up to the last at-sign (@) will be interpreted as a package name and ignored (this is exclusively
#   for compatability with existing Sentry setups; since bugsink releases are per-project package info is not needed)
#
# Note: When transitioning between version schemes, bugsink will "Just Work". In particular, releases detected by
# bugsink before the switch will precede those occurring after the switch. The typical scenario involves a
# straightforward shift from a state of "being too lazy to set up and merely using hashes" to adopting semver.
#
# † semver is defined as per the Python `semver` package, which also defines the ordering.
