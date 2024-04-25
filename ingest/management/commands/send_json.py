import io
import uuid

import time
import json
import requests
import jsonschema

from django.core.management.base import BaseCommand
from django.conf import settings

from compat.dsn import get_store_url, get_envelope_url, get_header_value
from bugsink.streams import compress_with_zlib, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE

from projects.models import Project


class Command(BaseCommand):
    help = "Send raw events to a sentry-compatible server; events can be sources from the filesystem or your DB."

    def add_arguments(self, parser):
        parser.add_argument("--dsn")
        parser.add_argument("--valid-only", action="store_true")
        parser.add_argument("--fresh-id", action="store_true")
        parser.add_argument("--fresh-timestamp", action="store_true")
        parser.add_argument("--compress", action="store", choices=["gzip", "deflate", "br"], default=None)
        parser.add_argument("--use-envelope", action="store_true")
        parser.add_argument("kind", action="store", help="The kind of object (filename, project, issue, event)")
        parser.add_argument("identifiers", nargs="+")

    def is_valid(self, data, identifier):
        if "event_id" not in data:
            self.stderr.write("%s %s" % ("Probably not a (single) event", identifier))
            return False

        if "platform" not in data:
            # in a few cases this value isn't set either in the sentry test data but I'd rather ignore those...
            # because 'platform' is such a valuable piece of info while getting a sense of the shape of the data
            self.stderr.write("%s %s" % ("Platform not set", identifier))
            return False

        if data.get("type", "") == "transaction":
            # kinda weird that this is in the "type" field rather than endpoint/envelope but who cares, that's
            # where the info lives and we use it as an indicator to skip
            self.stderr.write("%s %s" % ("We don't do transactions", identifier))
            return False

        if data.get('profile'):
            # yet another case of undocumented behavior that I don't care about
            # ../sentry-current/static/app/utils/profiling/profile/formats/node/trace.json
            self.stderr.write("%s %s" % ("124", identifier))
            return False

        if data.get('message'):
            # yet another case of undocumented behavior that I don't care about (top-level "message")
            # ../glitchtip/events/test_data/py_hi_event.json
            self.stderr.write("%s %s" % ("asdf", identifier))
            return False

        try:
            with open(settings.BASE_DIR / 'api/event.schema.json', 'r') as f:
                schema = json.loads(f.read())
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            self.stderr.write("%s %s %s" % ("still not ok at", repr(e), identifier))
            return False

        return True

    def handle(self, *args, **options):
        compress = options['compress']
        use_envelope = options['use_envelope']
        dsn = options['dsn']

        successfully_sent = []

        kind = options["kind"]

        if kind == "filename":
            for json_filename in options["identifiers"]:
                with open(json_filename) as f:
                    print("considering", json_filename)
                    try:
                        data = json.loads(f.read())
                    except Exception as e:
                        self.stderr.write("%s %s %s" % ("Not JSON", json_filename, str(e)))
                        continue

                    if self.send_to_server(dsn, options, json_filename, data, use_envelope, compress):
                        successfully_sent.append(json_filename)

        elif kind == "project":
            for project_id in options["identifiers"]:
                print("considering", project_id)
                project = Project.objects.get(pk=project_id)
                for event in project.event_set.all():
                    data = json.loads(event.data)
                    if self.send_to_server(dsn, options, str(event.id), data, use_envelope, compress):
                        successfully_sent.append(event.id)

        else:
            self.stderr.write("Unknown kind of data %s" % kind)
            exit(1)

        print("Successfuly sent to server")
        for filename in successfully_sent:
            print(filename)

    def send_to_server(self, dsn, options, identifier, data, use_envelope, compress):
        if "timestamp" not in data or options["fresh_timestamp"]:
            # weirdly enough a large numer of sentry test data don't actually have this required attribute set.
            # thus, we set it to something arbitrary on the sending side rather than have our server be robust
            # for it.

            # If promted, we just update the timestamp to 'now' to be able to avoid any 'ignore old stuff'
            # filters (esp. on hosted sentry when we want to see anything over there)
            data["timestamp"] = time.time()

        if options["fresh_id"]:
            data["event_id"] = uuid.uuid4().hex

        if options["valid_only"] and not self.is_valid(data, identifier):
            return False

        try:
            headers = {
                "Content-Type": "application/json",
                "X-Sentry-Auth": get_header_value(dsn),
                "X-BugSink-DebugInfo": identifier,  # TODO do we want to send non-filename identifiers too?
            }
            data_bytes = json.dumps(data).encode("utf-8")
            if use_envelope:
                data_bytes = b'{}\n{"type": "event"}\n' + data_bytes  # the smallest possible envelope.

            if compress in ["gzip", "deflate"]:
                if compress == "gzip":
                    headers["Content-Encoding"] = "gzip"
                    wbits = WBITS_PARAM_FOR_GZIP

                else:
                    headers["Content-Encoding"] = "deflate"
                    wbits = WBITS_PARAM_FOR_DEFLATE

                compressed_data = io.BytesIO()
                compress_with_zlib(io.BytesIO(data_bytes), compressed_data, wbits)

                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=compressed_data.getvalue(),
                )

            else:
                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=data_bytes,
                )

            response.raise_for_status()
            return True
        except Exception as e:
            raise
            self.stderr.write("Error %s, %s" % (e, getattr(getattr(e, 'response', None), 'content', None)))
            return False
