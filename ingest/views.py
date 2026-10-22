from collections import defaultdict
import uuid
import os
import logging
from datetime import datetime, timezone
import json

from django.shortcuts import get_object_or_404
from django.views import View
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test

from compat.auth import parse_auth_header_value
from compat.dsn import get_sentry_key, build_dsn

from projects.models import Project
from bugsink.streams import (
    content_encoding_reader, MaxDataReader, MaxDataWriter, NullWriter, MaxLengthExceeded,
    handle_request_content_encoding)
from bugsink.app_settings import get_settings
from bugsink.utils import set_path

from compat.timestamp import format_timestamp
from bsmain.utils import b108_makedirs
from phonehome.models import Installation

from sentry_sdk_extensions import capture_or_log_exception

from .parsers import StreamingEnvelopeParser, ParseError
from .filestore import get_filename_for_event_id
from .tasks import digest
from .digestion import is_quota_still_exceeded
from .models import StoreEnvelope, DontStoreEnvelope, Envelope


HTTP_429_TOO_MANY_REQUESTS = 429
HTTP_400_BAD_REQUEST = 400
HTTP_404_NOT_FOUND = 404
HTTP_413_CONTENT_TOO_LARGE = 413
HTTP_501_NOT_IMPLEMENTED = 501

logger = logging.getLogger("bugsink.ingest")
performance_logger = logging.getLogger("bugsink.performance.ingest")


@method_decorator(csrf_exempt, name='dispatch')
class BaseIngestAPIView(View):

    @staticmethod
    def _set_cors_headers(response):
        # For in-browser SDKs, we need to set the CORS headers, because if we don't, the browser will block the response
        # from being read and print an error in the console; the longer version is:
        #
        # CORS protects the user of a browser from some random website "A" sending requests to the API of some site "B";
        # implemented by the the browser enforcing the "Access-Control-Allow-Origin" response header as set by server B.
        # In this case, the "other website B" is the Bugsink server, and the "random website A" is the application that
        # is being monitored. The user has no relationship with the Bugsink API (there's nothing to protect), so we need
        # to tell the browser to not protect against Bugsink data from reaching the monitored application, i.e.
        # Access-Control-Allow-Origin: *.

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"

        response["Access-Control-Allow-Headers"] = (
            # The following 2 headers are actually understood by us:
            "Content-Type, X-Sentry-Auth, "

            # The following list of headers may be sent by Sentry SDKs. Even if we don't use them, we list them, because
            # any not-listed header is not allowed by the browser and would trip the CORS protection:
            "X-Requested-With, Origin, Accept, Authentication, Authorization, Content-Encoding, sentry-trace, "
            "baggage, X-CSRFToken"
        )
        response["Access-Control-Expose-Headers"] = "X-Sentry-Rate-Limits"

        return response

    def options(self, request, project_pk=None):
        # This is a CORS preflight request; we just return the headers that the browser expects. (we _could_ check for
        # the Origin, Request-Method, etc. headers, but we don't need to)
        result = HttpResponse()
        self._set_cors_headers(result)
        result["Access-Control-Max-Age"] = "3600"  # tell browser to cache to avoid repeated preflight requests
        return result

    def post(self, request, project_pk=None):
        try:
            return self._set_cors_headers(self._post(request, project_pk))
        except MaxLengthExceeded as e:
            return self._set_cors_headers(JsonResponse({"message": str(e)}, status=HTTP_413_CONTENT_TOO_LARGE))
        except ValidationError as e:
            return self._set_cors_headers(JsonResponse({"message": str(e)}, status=HTTP_400_BAD_REQUEST))
        except ParseError as e:
            return self._set_cors_headers(JsonResponse({"message": str(e)}, status=HTTP_400_BAD_REQUEST))

    @classmethod
    def get_sentry_key_for_request(cls, request):
        # we simply pick the first authentication mechanism that matches, rather than raising a SuspiciousOperation as
        # sentry does (I found the supplied reasons unconvincing). See https://github.com/getsentry/relay/pull/602

        # "In situations where it's not possible to send [..] header, it's possible [..] values via the querystring"
        # https://github.com/getsentry/develop/blob/b24a602de05b/src/docs/sdk/overview.mdx#L171
        if "sentry_key" in request.GET:
            return request.GET["sentry_key"]

        # Sentry used to support HTTP_AUTHORIZATION too, but that is unused since Sept. 27 2011
        if "HTTP_X_SENTRY_AUTH" in request.META:
            auth_dict = parse_auth_header_value(request.META["HTTP_X_SENTRY_AUTH"])
            return auth_dict.get("sentry_key")

        raise PermissionDenied("Unable to find authentication information")

    @classmethod
    def get_project(cls, project_pk, sentry_key):
        try:
            return Project.objects.get(pk=project_pk, sentry_key=sentry_key, is_deleted=False)
        except Project.DoesNotExist:
            # We don't distinguish between "project not found" and "key incorrect"; there's no real value in that from
            # the user perspective (they deal in dsns). Additional advantage: no need to do constant-time-comp on
            # project.sentry_key for security reasons in that case.
            #
            # The dsn we show is reconstructed _as we understand it at this point in the code_, which is precisely what
            # you want to show as a first step towards debugging issues with SDKs with faulty authentication (a rather
            # common scenario).
            dsn = build_dsn(str(get_settings().BASE_URL), project_pk, sentry_key)
            raise PermissionDenied("Project not found or key incorrect: %s" % dsn) from None

    @classmethod
    def get_project_for_request(cls, project_pk, request):
        sentry_key = cls.get_sentry_key_for_request(request)
        return cls.get_project(project_pk, sentry_key)

    @classmethod
    def cleanup_ingestion_files(cls, ingestion_id):
        for filetype in ["event", "minidump"]:
            filename = get_filename_for_event_id(ingestion_id, filetype=filetype)
            try:
                os.unlink(filename)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning("Failed to clean up ingestion file %s", filename, exc_info=e)

    @classmethod
    def _minidump_post_data(cls, request):
        event_data = {}
        extra_data = {}

        for key, value in request.POST.items():
            # Additionally,  you can set all attributes corresponding to the Sentry event interface in a sentry field...
            if key == "sentry":
                # > This field either accepts JSON data...
                try:
                    payload = json.loads(value)
                    event_data.update(payload)
                except Exception as e:
                    capture_or_log_exception(e, logger)

            elif key.startswith("sentry[") and key.endswith("]"):
                # > ... or its values can be flattened with the bracket syntax.
                parts = key[len("sentry["):-1].split("][")
                set_path(event_data, parts, value)
            else:
                # > fields to the upload HTTP request [..] will be collected in the "Extra Data" section
                extra_data[key] = value

        if extra_data:
            event_data.setdefault("extra", {}).update(extra_data)

        return event_data

    @classmethod
    def process_minidump(cls, ingested_at, ingestion_id, minidump_bytes, project, request):
        # This is for the "pure" minidump case, i.e. full separate event (however: event data/extra data _can_ be
        # provided via POST).
        performance_logger.info("ingested minidump with %s bytes", len(minidump_bytes))

        # NOTE: the sentry-native SDK (at least when crashpad-powered) sends a 'guid' request.POST field; we don't use
        # this yet and AFAICT Sentry doesn't either; AFAICT it's per-binary (not per-event), so the obvious target would
        # be "user".
        event_id = uuid.uuid4().hex
        event_data = cls._minidump_post_data(request)

        event_data["event_id"] = event_id
        event_data["platform"] = "native"
        event_data["errors"] = []

        filename = get_filename_for_event_id(ingestion_id)
        b108_makedirs(os.path.dirname(filename))
        with open(filename, 'w') as f:
            json.dump(event_data, f)

        with open(get_filename_for_event_id(ingestion_id, filetype="minidump"), "wb") as f:
            f.write(minidump_bytes)

        event_metadata = cls.get_event_meta(event_data["event_id"], ingested_at, ingestion_id, request, project)
        event_metadata["has_minidump"] = True
        digest.delay(event_data["event_id"], event_metadata)

        return event_id

    @classmethod
    def get_event_meta(cls, event_id, ingested_at, ingestion_id, request, project):
        # .get(..) -- don't want to crash on this and it's non-trivial to find a source that tells me with certainty
        # that the REMOTE_ADDR is always in request.META (it probably is in practice)
        remote_addr = request.META.get("REMOTE_ADDR")

        return {
            "event_id": event_id,
            "project_id": project.id,
            "ingested_at": format_timestamp(ingested_at),
            "ingestion_id": ingestion_id,
            "remote_addr": remote_addr,
        }



class IngestEventAPIView(BaseIngestAPIView):

    def _post(self, request, project_pk=None):
        # This endpoint is deprecated. Personally, I think it's the simpler (and given my goals therefore better) of the
        # two, but fighting windmills and all... given that it's deprecated, I'm not going to give it quite as much love
        # (at least for now).
        #
        # The main point of "inefficiency" is that the event data is parsed twice: once here (to get the event_id), and
        # once in the actual digest.delay()
        ingested_at = datetime.now(timezone.utc)
        ingestion_id = str(uuid.uuid4())

        installation = Installation.objects.get()
        if is_quota_still_exceeded(installation, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        project = self.get_project_for_request(project_pk, request)
        if is_quota_still_exceeded(project, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        event_data_bytes = MaxDataReader(
            "MAX_EVENT_SIZE", content_encoding_reader(MaxDataReader("MAX_EVENT_COMPRESSED_SIZE", request))).read()

        performance_logger.info("ingested event with %s bytes", len(event_data_bytes))

        try:
            event_data = json.loads(event_data_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ParseError("invalid JSON in event: %s" % e)

        if "event_id" not in event_data:
            event_data["event_id"] = uuid.uuid4().hex
        filename = get_filename_for_event_id(ingestion_id)
        b108_makedirs(os.path.dirname(filename))
        with open(filename, 'w') as f:
            json.dump(event_data, f)

        event_metadata = self.get_event_meta(event_data["event_id"], ingested_at, ingestion_id, request, project)

        digest.delay(event_data["event_id"], event_metadata)

        return JsonResponse({"id": event_data["event_id"]})


class IngestEnvelopeAPIView(BaseIngestAPIView):

    def post(self, request, project_pk=None):
        response = super().post(request, project_pk)

        # We repurpose the Sentry rate-limits header to indicate lack of support for transaction & span.
        rate_limits = "86400:transaction;span:organization"

        if response.status_code == HTTP_429_TOO_MANY_REQUESTS:
            # X-Sentry-Rate-Limits takes precedence over the generic backoff implied by a bare 429.
            rate_limits = "60::key, " + rate_limits

        response["X-Sentry-Rate-Limits"] = rate_limits
        return response

    def _post(self, request, project_pk=None):
        ingested_at = datetime.now(timezone.utc)
        ingestion_id = str(uuid.uuid4())

        input_stream = MaxDataReader("MAX_ENVELOPE_SIZE", content_encoding_reader(
            MaxDataReader("MAX_ENVELOPE_COMPRESSED_SIZE", request)))

        # note: we use the unvalidated (against DSN) "project_pk"; b/c of the debug-nature we assume "not a problem"
        input_stream = StoreEnvelope(ingested_at, project_pk, input_stream) if get_settings().KEEP_ENVELOPES > 0 \
            else DontStoreEnvelope(input_stream)

        try:
            return self._post2(request, input_stream, ingested_at, ingestion_id, project_pk)
        except Exception:
            self.cleanup_ingestion_files(ingestion_id)
            raise
        finally:
            # storing stuff in the DB on-ingest (rather than on digest-only) is not "as architected"; it's only
            # acceptible because this is a debug-only thing which is turned off by default; but even for me and other
            # debuggers the trade-off may not be entirely worth it. One way forward might be: store in Filesystem
            # instead.
            #
            # note: in finally, so this happens even for all paths, including errors and 404 (i.e. wrong DSN). By design
            # b/c the error-paths are often the interesting ones when debugging. We even store when over quota (429),
            # that's more of a trade-off to avoid adding extra complexity for a debug-tool. Also: because this touches
            # the DB again (in finally, so always) even when an error occurs, it may occlude other problems. ("dirty
            # transaction" in the DB).
            input_stream.store()

    def _post2(self, request, input_stream, ingested_at, ingestion_id, project_pk=None):
        # Note: wrapping the COMPRESSES_SIZE checks arount request makes it so that when clients do not compress their
        # requests, they are still subject to the (smaller) maximums that apply pre-uncompress. This is exactly what we
        # want.
        parser = StreamingEnvelopeParser(input_stream)

        envelope_headers = parser.get_envelope_headers()

        # Getting the installation & project is the only DB-touching (a read) we do before we start reading/writing in
        # digest_event in TASK_ALWAYS_EAGER mode. Notes on transactions:
        #
        # * we could add `durable_atomic` here for explicitness / if we ever do more than one read (for consistent
        #   snapshots. As it stands, not needed. (I believe this is implicit due to Django or even sqlite itself)
        # * In TASK_ALWAYS_EAGER mode we don't suffer from locks b/c sqlite upgrades read to write; I've tested this by
        #   adding sleep statements between the read/writes. I believe this is b/c of our immediate_atomic on
        #   digest_event. When removing that, and wrapping all of the present method in `durable_atomic`, read-write
        #   upgrades indeed fail.
        # * digest_event gets its own `project`, so there's no cross-transaction "pollution".
        # * Road not taken: pulling `immediate_atomic` up to the present level in TASK_ALWAYS_EAGER mode. This allows
        #   for passing of project between the 2 methods, but the added complexity (conditional transactions both here
        #   and in digest_event) is not worth it for a mode that is non-production anyway.
        installation = Installation.objects.get()
        if is_quota_still_exceeded(installation, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        if "dsn" in envelope_headers:
            # as in get_sentry_key_for_request, we don't verify that the DSN contains the project_pk, for the same
            # reason ("reasons unconvincing")
            project = self.get_project(project_pk, get_sentry_key(envelope_headers["dsn"]))
        else:
            project = self.get_project_for_request(project_pk, request)

        if is_quota_still_exceeded(project, ingested_at):
            # Sentry has x-sentry-rate-limits, but for now 429 is just fine. Client-side this is implemented as a 60s
            # backoff.
            #
            # Note "what's the use of this?": in my actual setups I have observed that we're almost entirely limited by
            # (nginx's) SSL processing on-ingest, and that digest is (almost) able to keep up. Because of request
            # buffering, the cost of such processing will already have been incurred once you reach this point. So is
            # the entire idea of quota useless? No, because the SDK will generally back off on 429, this does create
            # some relief. Also: avoid backlogging the digestion pipeline.
            #
            # Another aspect is: the quota serve as a first threshold for retention/evictions, i.e. some quota will mean
            # that retention is not too heavily favoring "most recent" when there are very many requests coming in.
            #
            # Note that events that exceed the quota will not be seen (not even counted) in any way; if we ever want to
            # do that we could make a specific task for it and delay that here (at a limited performance cost, but
            # keeping with the "don't block the main DB on-ingest" design)
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        def factory(item_headers):
            type_ = item_headers.get("type")

            if ((type_ not in ["event", "attachment"]) or
                    (item_headers.get("type") == "attachment" and
                     item_headers.get("attachment_type") != "event.minidump") or
                    (item_headers.get("type") == "attachment" and
                     item_headers.get("attachment_type") == "event.minidump" and
                     not get_settings().FEATURE_MINIDUMPS)):

                # non-event/minidumps can be discarded; (the somewhat arbitrary size limit is no problem because we have
                # the envelope limit to protect us, and we incur almost no cost (NullWriter))
                return MaxDataWriter("MAX_ATTACHMENT_SIZE", NullWriter())

            # envelope_headers["event_id"] is required when type in ["event", "attachment"] per the spec (and takes
            # precedence over the payload's event_id), so we can rely on it having been set.
            if "event_id" not in envelope_headers:
                raise ParseError("event_id not found in envelope headers")

            try:
                # validate that the event_id is a valid UUID as per the spec (validate at the edge)
                uuid.UUID(envelope_headers["event_id"])
            except ValueError:
                raise ParseError("event_id in envelope headers is not a valid UUID")

            filetype = "event" if type_ == "event" else "minidump"
            filename = get_filename_for_event_id(ingestion_id, filetype=filetype)
            b108_makedirs(os.path.dirname(filename))

            size_conf = "MAX_EVENT_SIZE" if type_ == "event" else "MAX_ATTACHMENT_SIZE"
            return MaxDataWriter(size_conf, open(filename, 'wb'))

        # We ingest the whole envelope first and organize by type; this enables "digest once" across envelope-parts
        items_by_type = defaultdict(list)
        for item_headers, output_stream in parser.get_items(factory):
            type_ = item_headers.get("type")
            if type_ not in ["event", "attachment"]:
                logger.info("skipping non-supported envelope item: %s", item_headers.get("type"))
                continue

            if type_ == "attachment" and item_headers.get("attachment_type") != "event.minidump":
                logger.info("skipping non-supported attachment type: %s", item_headers.get("attachment_type"))
                continue

            performance_logger.info("ingested %s with %s bytes", type_, output_stream.bytes_written)
            items_by_type[type_].append(output_stream)

        event_count = len(items_by_type.get("event", []))
        minidump_count = len(items_by_type.get("attachment", [])) if get_settings().FEATURE_MINIDUMPS else 0

        if event_count + minidump_count == 0:
            logger.info("no event or minidump found in envelope, ignoring this envelope.")
            # event_id is only required in envelope headers when event/attachment items are present (enforced in
            # factory), so it may be absent here; only echo it back when the SDK actually provided one.
            if "event_id" in envelope_headers:
                return JsonResponse({"id": envelope_headers["event_id"]})
            return HttpResponse()

        if event_count > 1 or minidump_count > 1:
            logger.info(
                "can only deal with one event/minidump per envelope but found %s/%s, ignoring this envelope.",
                event_count, minidump_count)
            self.cleanup_ingestion_files(ingestion_id)
            return JsonResponse({"id": envelope_headers["event_id"]})

        event_metadata = self.get_event_meta(envelope_headers["event_id"], ingested_at, ingestion_id, request, project)

        if event_count == 1:
            if minidump_count == 1:
                event_metadata["has_minidump"] = True
            digest.delay(envelope_headers["event_id"], event_metadata)

        else:
            # as it stands, we implement the minidump->event path for the minidump-only case on-ingest; we could push
            # this to a task too if needed or for reasons of symmetry.
            with open(get_filename_for_event_id(ingestion_id, filetype="minidump"), 'rb') as f:
                minidump_bytes = f.read()

            # TODO: error handling
            # NOTE "The file should start with the MDMP magic bytes." is not checked yet.
            self.process_minidump(ingested_at, ingestion_id, minidump_bytes, project, request)

        return JsonResponse({"id": envelope_headers["event_id"]})


# Just a few thoughts on the relative performance of the main building blocks of dealing with Envelopes, and how this
# affect our decision making. On my local laptop (local loopback, django dev server), with a single 50KiB event, I
# measured the following approximate timtings:
# 0.00001s just get the bytes
# 0.0002s get bytes & gunzip
# 0.0005s get bytes, gunzip & json load
#
# The goal of having an ingest/digest split is to keep the server responsive in times of peek load. It is _not_ to have
# get crazy good throughput numbers (because ingest isn't the bottleneck anyway).
#
# One consideration was: should we just store the compressed envelope on-upload. Answer, given the numbers above: not
# needed, fine to unpack. This is also prudent from the perspective of storage, because the envelope may contain much
# more stuff that we don't care about (up to 20MiB compressed) whereas the max event size (uncompressed) is 1MiB.
# Another advantage: this allows us to raise the relevant Header parsing and size limitation Exceptions to the SDKs.
#


class IngestSecurityAPIView(BaseIngestAPIView):
    # Browser-emitted CSP violation reports, posted via the `report-uri` directive. We translate the report into an
    # event and run it through the same digest pipeline as everything else so it reuses quota, retention, grouping, etc.
    #
    # Two shape decisions worth calling out:
    #
    # * Auth via `?sentry_key=` query param. Browsers can't set custom headers on CSP report POSTs, so the X-Sentry-Auth
    #   path isn't available to us here. `BaseIngestAPIView.get_sentry_key_for_request` already prefers the query param,
    #   so this falls out for free.
    #
    # * Strict on Content-Type: we only accept `application/csp-report` (the value the spec mandates and that browsers
    #   actually send). The `report-uri` flow is tightly defined; accepting `application/json` too would silently mask
    #   misconfigured emitters/proxies and we'd rather reject early.
    #
    # Not yet supported: `application/reports+json` (the newer Reporting API / `report-to` directive). Browsers still
    # emit the old `report-uri` format widely enough that the minimum viable version covers most cases.

    CONTENT_TYPE = "application/csp-report"

    def _post(self, request, project_pk=None):
        if request.content_type != self.CONTENT_TYPE:
            return JsonResponse(
                {"message": "Content-Type must be %s" % self.CONTENT_TYPE},
                status=HTTP_400_BAD_REQUEST,
            )

        ingested_at = datetime.now(timezone.utc)
        ingestion_id = str(uuid.uuid4())

        installation = Installation.objects.get()
        if is_quota_still_exceeded(installation, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        project = self.get_project_for_request(project_pk, request)
        if is_quota_still_exceeded(project, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        # CSP reports are small by spec; the cap is a defense against abuse, not a real-world ceiling. Oversized bodies
        # raise MaxLengthExceeded, which BaseIngestAPIView.post turns into a 413.
        body_bytes = MaxDataReader("MAX_CSP_REPORT_SIZE", request).read()
        performance_logger.info("ingested CSP report with %s bytes", len(body_bytes))

        try:
            payload = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ParseError("invalid JSON in CSP report: %s" % e)

        if not isinstance(payload, dict) or not isinstance(payload.get("csp-report"), dict):
            raise ParseError("CSP report must be a JSON object with a 'csp-report' object")

        report = payload["csp-report"]

        event_id = uuid.uuid4().hex
        event_data = self._csp_report_to_event_data(event_id, report, ingested_at)

        filename = get_filename_for_event_id(ingestion_id)
        b108_makedirs(os.path.dirname(filename))
        with open(filename, 'w') as f:
            json.dump(event_data, f)

        event_metadata = self.get_event_meta(event_id, ingested_at, ingestion_id, request, project)
        digest.delay(event_id, event_metadata)

        return HttpResponse()

    @staticmethod
    def _report_value_as_string(report, key):
        value = report.get(key)
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _csp_report_to_event_data(event_id, report, ingested_at):
        # Older browsers only send `violated-directive` (which includes the source list, e.g. "script-src 'self'");
        # newer ones also send `effective-directive` (just the directive name). Prefer the latter, fall back to the
        # first token of the former. This is the value we group on, so consistency across browsers matters.
        violated_directive = IngestSecurityAPIView._report_value_as_string(report, "violated-directive") or ""
        effective_directive = (
            IngestSecurityAPIView._report_value_as_string(report, "effective-directive")
            or violated_directive.split(" ", 1)[0]
            or "<unknown>"
        )
        blocked_uri = IngestSecurityAPIView._report_value_as_string(report, "blocked-uri") or "<unknown>"

        # type/value drive the title via get_title_for_exception_type_and_value -> "CSP: blocked X (directive)".
        # fingerprint drives grouping (overrides the default grouper) so each unique (directive, blocked-uri) pair
        # becomes one issue rather than one per page that triggered it.
        event_data = {
            "event_id": event_id,
            "timestamp": ingested_at.timestamp(),
            "platform": "javascript",
            "logger": "csp",
            "level": "warning",
            "exception": {
                "values": [{
                    "type": "CSP",
                    "value": "blocked %s (%s)" % (blocked_uri, effective_directive),
                }],
            },
            "fingerprint": ["csp", effective_directive, blocked_uri],
            "contexts": {
                "csp": {
                    k: report[k] for k in (
                        "document-uri", "referrer", "blocked-uri", "violated-directive", "effective-directive",
                        "original-policy", "disposition", "source-file", "line-number", "column-number",
                        "status-code", "script-sample",
                    ) if k in report
                },
            },
        }

        document_uri = IngestSecurityAPIView._report_value_as_string(report, "document-uri")
        if document_uri:
            event_data["request"] = {"url": document_uri}
            referrer = IngestSecurityAPIView._report_value_as_string(report, "referrer")
            if referrer:
                event_data["request"]["headers"] = {"Referer": referrer}

        return event_data


class MinidumpAPIView(BaseIngestAPIView):
    # A Base "Ingest" APIView in the sense that it reuses some key building blocks (auth).
    # I'm not 100% sure whether "philosophically" the minidump endpoint is also "ingesting"; we'll see.

    def post(self, request, project_pk=None):
        if not get_settings().FEATURE_MINIDUMPS:
            return JsonResponse({"detail": "minidumps not enabled"}, status=HTTP_404_NOT_FOUND)

        # not reusing the CORS stuff here; minidump-from-browser doesn't make sense.

        # NOTE for multipart requests this is actually interpreted as the total size of the request body, which
        # includes other form fields and multipart formatting i.e. we're slightly more strict but the difference is
        # negligible so we use the simpler solution here.
        handle_request_content_encoding(request, "MAX_ATTACHMENT_SIZE")

        ingested_at = datetime.now(timezone.utc)

        installation = Installation.objects.get()
        if is_quota_still_exceeded(installation, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        project = self.get_project_for_request(project_pk, request)
        if is_quota_still_exceeded(project, ingested_at):
            return HttpResponse(status=HTTP_429_TOO_MANY_REQUESTS)

        try:
            if "upload_file_minidump" not in request.FILES:
                return JsonResponse({"detail": "upload_file_minidump not found"}, status=HTTP_400_BAD_REQUEST)

            minidump_bytes = request.FILES["upload_file_minidump"].read()
            event_id = self.process_minidump(ingested_at, uuid.uuid4().hex, minidump_bytes, project, request)

            return JsonResponse({"id": event_id})
        except MaxLengthExceeded as e:
            return JsonResponse({"detail": str(e)}, status=HTTP_413_CONTENT_TOO_LARGE)
        except Exception as e:
            # we're still figuring out what this endpoint should do; so we log errors to learn from them while saying
            # to the client "400 Bad Request" if we can't handle their stuff.
            capture_or_log_exception(e, logger)
            return JsonResponse({"detail": str(e)}, status=HTTP_400_BAD_REQUEST)


@user_passes_test(lambda u: u.is_superuser)
def download_envelope(request, envelope_id=None):
    envelope = get_object_or_404(Envelope, pk=envelope_id)
    response = HttpResponse(envelope.data, content_type="application/x-sentry-envelope")
    response["Content-Disposition"] = f'attachment; filename="envelope-{envelope_id}.envelope"'
    return response
