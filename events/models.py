import json
import uuid

from django.db import models

from projects.models import Project
from compat.timestamp import parse_timestamp

from issues.utils import get_title_for_exception_type_and_value


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

    # null=True reveals our doubts about "should this always be set, or even be done at all?"
    ingested_event = models.ForeignKey("ingest.DecompressedEvent", null=True, on_delete=models.SET_NULL)

    server_side_timestamp = models.DateTimeField(db_index=True, blank=False, null=False)

    # not actually expected to be null, but we want to be able to delete issues without deleting events (cleanup later)
    issue = models.ForeignKey("issues.Issue", blank=False, null=True, on_delete=models.SET_NULL)

    # > Required. Hexadecimal string representing a uuid4 value. The length is exactly 32 characters. Dashes are not
    # > allowed. Has to be lowercase.
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

    # TODO simply not done yet; it's not mentioned in the main page for event so I missed it on the first pass
    # request =

    # > Distributions are used to disambiguate build or deployment variants of the same release of an application. For
    # > example, the dist can be the build number of an Xcode build or the version code of an Android build.
    # max_length was deduced from current (late 2023) Sentry's ArtifactBundleFlatFileIndex model
    dist = models.CharField(max_length=64, blank=True, null=False, default="")

    # TODO because a list
    # > Optional. A map or list of tags for this event. Each tag must be less than 200 characters.
    # tags

    # > The environment name, such as production or staging. The default value should be production.
    # max_length was deduced from current (late 2023) Sentry's GroupRelease model
    environment = models.CharField(max_length=64, blank=True, null=False, default="")

    # TODO because a list
    # > A list of relevant modules and their versions.
    # modules

    # Not done because deemed irrelevant (for now)
    # > An arbitrary mapping of additional metadata to store with the event.
    # extra =

    # TODO because a list
    # > A list of strings used to dictate the deduplication of this event.
    # fingerprint

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

    # 1-based, because this is for human consumption only, and using 0-based internally when we don't actually do
    # anything with this value other than showing it to humans is super-confusing. Sorry Dijkstra!
    ingest_order = models.IntegerField(blank=False, null=False)

    class Meta:
        unique_together = (("project", "event_id"),)
        # index_together = (("group_id", "datetime"),)  TODO seriously think about indexes

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
    def from_ingested(cls, ingested_event, ingest_order, issue, parsed_data, calculated_type, calculated_value):
        # 'from_ingested' may be a bit of a misnomer... the full 'from_ingested' is done in 'digest_event' in the views.
        # below at least puts the parsed_data in the right place, and does some of the basic object set up (FKs to other
        # objects etc).

        event, created = cls.objects.get_or_create(  # NOTE immediate creation... is this what we want?
            event_id=parsed_data["event_id"],
            project=ingested_event.project,
            defaults={
                'ingested_event': ingested_event,  # <= thoughts about defaults v.s. check-as-part-of-get go here :-)
                'issue': issue,
                'server_side_timestamp': ingested_event.timestamp,
                'data': json.dumps(parsed_data),

                'timestamp': parse_timestamp(parsed_data["timestamp"]),
                'platform': parsed_data["platform"],

                'level': maybe_empty(parsed_data.get("level", "")),
                'logger': maybe_empty(parsed_data.get("logger", "")),
                'transaction': maybe_empty(parsed_data.get("transaction", "")),

                'server_name': maybe_empty(parsed_data.get("server_name", "")),
                'release': maybe_empty(parsed_data.get("release", "")),
                'dist': maybe_empty(parsed_data.get("dist", "")),

                'environment': maybe_empty(parsed_data.get("environment", "")),

                'sdk_name': maybe_empty(parsed_data.get("", {}).get("name", "")),
                'sdk_version': maybe_empty(parsed_data.get("", {}).get("version", "")),

                'has_exception': "exception" in parsed_data,
                'has_logentry': "logentry" in parsed_data,

                'debug_info': ingested_event.debug_info,

                'calculated_type': calculated_type,
                'calculated_value': calculated_value,
                'ingest_order': ingest_order,
            }
        )
        return event, created
