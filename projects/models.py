from uuid import uuid4

from django.db import models


def uuid4_hex():
    return uuid4().hex


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
    sentry_key = models.CharField(max_length=32, unique=True, null=False, default=uuid4_hex)

    # We don't implement private_key because as of late 2023 the Sentry documentation says the following:
    # > The secret part of the DSN is optional and effectively deprecated. While clients will still honor it, if
    # > supplied, future versions of Sentry will entirely ignore it.
    # private_key = ...

    def __str__(self):
        return self.name
