import re
import json
import uuid

from django.db import models
from django.db.utils import IntegrityError
from django.db.models import Min, Max

from projects.models import Project
from compat.timestamp import parse_timestamp

from issues.utils import get_title_for_exception_type_and_value

from .retention import get_random_irrelevance


class Platform(models.TextChoices):
    AS3 = "as3"
    C = "c"
    CFML = "cfml"
    COCOA = "cocoa"
    CSHARP = "csharp"
    ELIXIR = "elixir"
    HASKELL = "haskell"
    GO = "go"
    GROOVY = "groovy"
    JAVA = "java"
    JAVASCRIPT = "javascript"
    NATIVE = "native"
    NODE = "node"
    OBJC = "objc"
    OTHER = "other"
    PERL = "perl"
    PHP = "php"
    PYTHON = "python"
    RUBY = "ruby"


class Level(models.TextChoices):
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


def maybe_empty(s):
    return "" if not s else s


class Event(models.Model):
    # Lines quotes with ">" are from the following to resources:
    # https://develop.sentry.dev/sdk/event-payloads/ (supposedly more human-readable)
    # https://develop.sentry.dev/sdk/event-payloads/types/ (more up-to-date and complete)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, help_text="Bugsink-internal")

    ingested_at = models.DateTimeField(blank=False, null=False)
    digested_at = models.DateTimeField(db_index=True, blank=False, null=False)

    # not actually expected to be null, but we want to be able to delete issues without deleting events (cleanup later)
    issue = models.ForeignKey("issues.Issue", blank=False, null=True, on_delete=models.SET_NULL)

    # The docs say:
    # > Required. Hexadecimal string representing a uuid4 value. The length is exactly 32 characters. Dashes are not
    # > allowed. Has to be lowercase.
    # But event.schema.json has this anyOf [..] null and only speaks of "it is strongly recommended to generate that
    # uuid4 clientside". In any case, we just rely on the envelope's event_id (required per the envelope spec).
    # Not a primary key: events may be duplicated across projects
    event_id = models.UUIDField(primary_key=False, null=False, editable=False, help_text="As per the sent data")
    project = models.ForeignKey(Project, blank=False, null=True, on_delete=models.SET_NULL)  # SET_NULL: cleanup 'later'

    data = models.TextField(blank=False, null=False)

    # > Indicates when the event was created in the Sentry SDK. The format is either a string as defined in RFC 3339 or
    # > a numeric (integer or float) value representing the number of seconds that have elapsed since the Unix epoch.
    timestamp = models.DateTimeField(db_index=True, blank=False, null=False)

    # > A string representing the platform the SDK is submitting from. [..] Acceptable values are [as defined below]
    platform = models.CharField(max_length=64, blank=False, null=False, choices=Platform.choices)

    # > ### Optional Attributes

    # > The record severity. Defaults to error. The value needs to be one on the supported level string values.
    level = models.CharField(max_length=len("warning"), blank=True, null=False, choices=Level.choices)

    # > The name of the logger which created the record.
    # max_length was deduced from current (late 2023) Sentry's Group model
    logger = models.CharField(max_length=64, blank=True, null=False, default="")  # , db_index=True)

    # > The name of the transaction which caused this exception. For example, in a web app, this might be the route name
    # max_length was deduced from current (late 2023) Sentry's code ("based on the maximum for transactions in relay")
    transaction = models.CharField(max_length=200, blank=True, null=False, default="")

    # Identifies the host from which the event was recorded.
    # https://stackoverflow.com/a/28918017/ says "Code should deal with hostnames up to 255 bytes long;"
    server_name = models.CharField(max_length=255, blank=True, null=False, default="")

    # > The release version of the application. Release versions must be unique across all projects in your
    # > organization. This value can be the git SHA for the given project, or a product identifier with a semantic
    # > version (suggested format my-project-name@1.0.0).
    # max_length was deduced from current (late 2023) Sentry's Transaction model
    release = models.CharField(max_length=250, blank=True, null=False, default="")

    # > Distributions are used to disambiguate build or deployment variants of the same release of an application. For
    # > example, the dist can be the build number of an Xcode build or the version code of an Android build.
    # max_length was deduced from current (late 2023) Sentry's ArtifactBundleFlatFileIndex model
    dist = models.CharField(max_length=64, blank=True, null=False, default="")

    # > The environment name, such as production or staging. The default value should be production.
    # max_length was deduced from current (late 2023) Sentry's GroupRelease model
    environment = models.CharField(max_length=64, blank=True, null=False, default="")

    # > Information about the Sentry SDK that generated this event.
    # max_length: In current (late 2023) Sentry this is implemented as an Interface (data TextField) so no real max
    sdk_name = models.CharField(max_length=255, blank=True, null=False, default="")
    sdk_version = models.CharField(max_length=255, blank=True, null=False, default="")

    # these 2 are perhaps temporary, I made them up myself. Idea: ability to get a sense of the shape of the data quicly
    has_exception = models.BooleanField(null=False)
    has_logentry = models.BooleanField(null=False)

    # this is a temporary(?), bugsink-specific value;
    debug_info = models.CharField(max_length=255, blank=True, null=False, default="")

    # denormalized/cached fields:
    calculated_type = models.CharField(max_length=255, blank=True, null=False, default="")
    calculated_value = models.CharField(max_length=255, blank=True, null=False, default="")
    # transaction = models.CharField(max_length=200, blank=True, null=False, default="")  defined first-class above
    last_frame_filename = models.CharField(max_length=255, blank=True, null=False, default="")
    last_frame_module = models.CharField(max_length=255, blank=True, null=False, default="")
    last_frame_function = models.CharField(max_length=255, blank=True, null=False, default="")

    # 1-based, because this is for human consumption only, and using 0-based internally when we don't actually do
    # anything with this value other than showing it to humans is super-confusing. Sorry Dijkstra!
    digest_order = models.PositiveIntegerField(blank=False, null=False)

    # irrelevance_for_retention is set on-ingest based on the number of available events for an issue; it is combined
    # with age-based-irrelevance to determine which events will be evicted when retention quota are met.
    irrelevance_for_retention = models.PositiveIntegerField(blank=False, null=False)
    never_evict = models.BooleanField(blank=False, null=False, default=False)

    # The following list of attributes are mentioned in the docs but are not attrs on our model (because we don't need
    # them to be [yet]):
    #
    # > Optional. A map or list of tags for this event. Each tag must be less than 200 characters.
    # tags
    #
    # > A list of relevant modules and their versions.
    # modules =
    #
    # > An arbitrary mapping of additional metadata to store with the event.
    # extra =
    #
    # > A list of strings used to dictate the deduplication of this event.
    # fingerprint
    #
    # (This one is mentioned on https://develop.sentry.dev/sdk/event-payloads/request/)
    # request =

    class Meta:
        unique_together = [
            ("project", "event_id"),
            ("issue", "digest_order"),
        ]
        indexes = [
            models.Index(fields=["project", "never_evict", "digested_at", "irrelevance_for_retention"]),
            models.Index(fields=["issue", "digested_at"]),
        ]

    def get_absolute_url(self):
        return f"/issues/issue/{ self.issue_id }/event/{ self.id }/"

    def get_raw_link(self):
        # for the admin
        return "/events/event/%s/raw/" % self.id

    def get_download_link(self):
        # for the admin
        return "/events/event/%s/download/" % self.id

    def title(self):
        return get_title_for_exception_type_and_value(self.calculated_type, self.calculated_value)

    @classmethod
    def from_ingested(cls, event_metadata, digested_at, digest_order, stored_event_count, issue, parsed_data,
                      denormalized_fields):

        # 'from_ingested' may be a bit of a misnomer... the full 'from_ingested' is done in 'digest_event' in the views.
        # below at least puts the parsed_data in the right place, and does some of the basic object set up (FKs to other
        # objects etc).

        irrelevance_for_retention = get_random_irrelevance(stored_event_count)

        try:
            event = cls.objects.create(
                event_id=event_metadata["event_id"],  # the metadata is the envelope's event_id, which takes precedence
                project_id=event_metadata["project_id"],
                issue=issue,
                ingested_at=event_metadata["ingested_at"],
                digested_at=digested_at,
                data=json.dumps(parsed_data),

                timestamp=parse_timestamp(parsed_data["timestamp"]),
                platform=parsed_data["platform"],

                level=maybe_empty(parsed_data.get("level", "")),
                logger=maybe_empty(parsed_data.get("logger", "")),
                # transaction=maybe_empty(parsed_data.get("transaction", "")), part of denormalized_fields

                server_name=maybe_empty(parsed_data.get("server_name", "")),
                release=maybe_empty(parsed_data.get("release", "")),
                dist=maybe_empty(parsed_data.get("dist", "")),

                environment=maybe_empty(parsed_data.get("environment", "")),

                sdk_name=maybe_empty(parsed_data.get("", {}).get("name", "")),
                sdk_version=maybe_empty(parsed_data.get("", {}).get("version", "")),

                has_exception="exception" in parsed_data,
                has_logentry="logentry" in parsed_data,

                debug_info=event_metadata["debug_info"],

                digest_order=digest_order,
                irrelevance_for_retention=irrelevance_for_retention,

                **denormalized_fields,
            )
            created = True
            return event, created
        except IntegrityError as e:
            assert re.match(
                r".*unique constraint failed.*events_event.*project_id.*events_event.*event_id", str(e).lower())
            return None, False

    def get_digest_order_bounds(self):
        if not hasattr(self, "_digest_order_bounds"):
            d = Event.objects.filter(issue_id=self.issue.id).aggregate(lo=Min("digest_order"), hi=Max("digest_order"))
            self._digest_order_bounds = d["lo"], d["hi"]
        return self._digest_order_bounds

    def has_prev(self):
        return self.digest_order > self.get_digest_order_bounds()[0]

    def has_next(self):
        return self.digest_order < self.get_digest_order_bounds()[1]
