import logging

from django.db import models

from bugsink.transaction import immediate_atomic
from bugsink.app_settings import get_settings

logger = logging.getLogger("bugsink.ingest")


class StoreEnvelope:
    def __init__(self, ingested_at, project_pk, request):
        self._read = b""

        self._ingested_at = ingested_at
        self._project_pk = project_pk

        self.request = request

    def read(self, size):
        result = self.request.read(size)
        if result:
            self._read += result
        return result

    def __getattr__(self, attr):
        return getattr(self.request, attr)

    # `immediate_atomic` here, rather than in the calling spot, to avoid its usage on the DontStoreEnvelope case.
    # Also: all the transaction stuff is kinda overkill anyway, for something that's completely unconnected to our real
    # data, i.e. can't really conflict... but in the sqlite world being explicit about where the transactions are is
    # always a good thing, i.e. keeps them small)
    @immediate_atomic()
    def store(self):
        # read the rest of the request; the regular .ingest() method breaks early by design
        self._read += self.request.read()

        if Envelope.objects.count() >= get_settings().KEEP_ENVELOPES:  # >= b/c about to add
            # -1 because 0-indexed; we delete including the boundary, so we'll have space for the new one
            boundary = Envelope.objects.order_by("-ingested_at")[get_settings().KEEP_ENVELOPES - 1]
            Envelope.objects.filter(ingested_at__lte=boundary.ingested_at).delete()

        envelope = Envelope.objects.create(
            ingested_at=self._ingested_at,
            project_pk=self._project_pk,
            data=self._read,
        )

        # arguably "debug", but if you turned StoreEnvelope on, you probably want to use its results "soon", and I'd
        # rather not have another thing for people to configure.
        logger.info("envelope stored, available at %s%s", str(get_settings().BASE_URL), envelope.get_absolute_url())


class DontStoreEnvelope:
    """conform to the same interface as StoreEnvelope, but don't store anything"""
    def __init__(self, request):
        self.request = request

    def __getattr__(self, attr):
        return getattr(self.request, attr)

    def store(self):
        pass


class Envelope(models.Model):
    # id is implied which makes it an Integer. Great for sorting

    ingested_at = models.DateTimeField(blank=False, null=False)

    # we just use PK to avoid passing Projects around for debug code, and avoid FK-constraints too.
    project_pk = models.IntegerField(blank=False)

    # binary, because we don't want to make any assumptions about what we get "over the wire" (whether it's even utf-8)
    data = models.BinaryField(blank=False, null=False)

    class Meta:
        indexes = [
            models.Index(fields=["ingested_at"]),
        ]

    def get_absolute_url(self):
        return f"/ingest/envelope/{self.pk}/"
