import io
import uuid
import brotli
import random

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
        parser.add_argument("--fresh-trace", action="store_true")
        parser.add_argument("--tag", nargs="*", action="append")
        parser.add_argument("--compress", action="store", choices=["gzip", "deflate", "br"], default=None)
        parser.add_argument("--use-envelope", action="store_true")
        parser.add_argument(
            "--x-forwarded-for", action="store",
            help="Set the X-Forwarded-For header to test whether your setup is properly ignoring it")
        parser.add_argument("kind", action="store", help="The kind of object (filename, project, issue, event)")
        parser.add_argument("identifiers", nargs="+")

    def is_valid(self, data, identifier):
        # In our (private) samples we often have this "_meta" field. I can't (quickly) find any documentation for it,
        # nor do I have any use for it myself (i.e. I don't display this info in templates). The quickest way to get
        # something to work is to just remove the info from the json. This comes with the drawback of changing data
        # on-validation, but for now that's an OK trade=off.
        if "_meta" in data:
            del data["_meta"]

        try:
            schema_filename = settings.BASE_DIR / 'api/event.schema.altered.json'
            with open(schema_filename, 'r') as f:
                schema = json.loads(f.read())

            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            best = jsonschema.exceptions.best_match([e])

            self.stderr.write("%s: %s %s" % (best.json_path, best.message, identifier))
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
                    data = event.get_parsed_data()
                    if self.send_to_server(dsn, options, str(event.id), data, use_envelope, compress):
                        successfully_sent.append(event.id)

        else:
            self.stderr.write("Unknown kind of data %s" % kind)
            exit(1)

        print("Successfuly sent to server")
        for filename in successfully_sent:
            print(filename)

    def send_to_server(self, dsn, options, identifier, data, use_envelope, compress):
        if options["fresh_timestamp"]:
            # If promted, we just update the timestamp to 'now' to be able to avoid any 'ignore old stuff'
            # filters (esp. on hosted sentry when we want to see anything over there)
            data["timestamp"] = time.time()

        if options["fresh_id"]:
            data["event_id"] = uuid.uuid4().hex

        if options["fresh_trace"]:
            if "contexts" not in data:
                data["contexts"] = {}
            if "trace" not in data["contexts"]:
                data["contexts"]["trace"] = {}

            # https://develop.sentry.dev/sdk/data-model/event-payloads/span/#attributes
            # > A random hex string with a length of 16 characters. [which is 8 bytes]
            data["contexts"]["trace"]["span_id"] = random.getrandbits(64).to_bytes(8, byteorder='big').hex()
            # > A random hex string with a length of 32 characters. [which is 16 bytes]
            data["contexts"]["trace"]["trace_id"] = random.getrandbits(128).to_bytes(16, byteorder='big').hex()

        if options["tag"]:
            if "tags" not in data:
                data["tags"] = {}

            for tag in options["tag"]:
                tag = tag[0]  # it's a list of lists... how to prevent this is not immediately clear
                k, v = tag.split(":", 1)
                data["tags"][k] = v

        if options["valid_only"] and not self.is_valid(data, identifier):
            return False

        try:
            headers = {
                "Content-Type": "application/json",
                "X-Sentry-Auth": get_header_value(dsn),
                # as it stands we always send identifier here, even if it's not a filename. Whether that's useful or
                # annoying is an open question, but no reason to change it for now
                "X-BugSink-DebugInfo": identifier,
            }

            if options["x_forwarded_for"]:
                headers["X-Forwarded-For"] = options["x_forwarded_for"]

            data_bytes = json.dumps(data).encode("utf-8")
            if use_envelope:
                # the smallest possible envelope:
                event_id = data.get("event_id", uuid.uuid4().hex)

                data_bytes = (b'{"event_id": "%s"}\n{"type": "event"}\n' % event_id.encode("utf-8") +
                              data_bytes)

            if compress in ["gzip", "deflate"]:
                if compress == "gzip":
                    headers["Content-Encoding"] = "gzip"
                    wbits = WBITS_PARAM_FOR_GZIP

                elif compress == "deflate":
                    headers["Content-Encoding"] = "deflate"
                    wbits = WBITS_PARAM_FOR_DEFLATE

                compressed_data = compress_with_zlib(io.BytesIO(data_bytes), wbits)
                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=compressed_data,
                )

            elif compress == "br":
                headers["Content-Encoding"] = "br"
                compressed_data = brotli.compress(data_bytes)
                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=compressed_data,
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
            self.stderr.write("Error %s, %s" % (e, getattr(getattr(e, 'response', None), 'content', None)))
            return False
