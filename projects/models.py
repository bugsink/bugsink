import uuid

from django.db import models
from django.conf import settings

from compat.dsn import build_dsn


class Project(models.Model):
    # id is implied which makes it an Integer; we would prefer a uuid but the sentry clients have int baked into the DSN
    # parser (we could also introduce a special field for that purpose but that's ugly too)

    name = models.CharField(max_length=255, blank=False, null=False)

    # sentry_key mirrors the "public" part of the sentry DSN. As of late 2023 Sentry's docs say the this about DSNs:
    #
    # > DSNs are safe to keep public because they only allow submission of new events and related event data; they do
    # > not allow read access to any information.
    #
    # The "because" in that sentence is dubious at least; however, I get why they say it, because they want to do JS and
    # native apps too, and there's really no way to do those without exposing (some) endpoint. Anyway, I don't think the
    # "public" key is public, and if you can help it it's always better to keep it private.
    sentry_key = models.UUIDField(editable=False, default=uuid.uuid4)

    # We don't implement private_key because as of late 2023 the Sentry documentation says the following:
    # > The secret part of the DSN is optional and effectively deprecated. While clients will still honor it, if
    # > supplied, future versions of Sentry will entirely ignore it.
    # private_key = ...

    # denormalized/cached fields below
    has_releases = models.BooleanField(editable=False, default=False)

    def __str__(self):
        return self.name

    @property
    def dsn(self):
        return build_dsn(settings.BASE_URL, self.id, self.sentry_key)

    """
    # TODO is this even more efficient?
    indexes = [
        models.Index(fields=["id", "sentry_key"]),
    ]
    """

    # alerting conditions
    alert_on_new_issue = models.BooleanField(default=True)
    alert_on_regression = models.BooleanField(default=True)
    alert_on_unmute = models.BooleanField(default=True)

    def get_latest_release(self):
        # TODO perfomance considerations... this can be denormalized/cached at the project level
        from releases.models import ordered_releases
        return list(ordered_releases(project=self))[-1]
