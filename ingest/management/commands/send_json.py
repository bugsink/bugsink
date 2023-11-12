import json
import requests
import jsonschema

from django.core.management.base import BaseCommand
from django.conf import settings

from compat.dsn import get_store_url, get_header_value


class Command(BaseCommand):
    help = "Quick and dirty command to load a bunch of events from e.g. the sentry test codebase"

    def add_arguments(self, parser):
        parser.add_argument("--dsn")
        parser.add_argument("json_files", nargs="+")

    def handle(self, *args, **options):
        dsn = options['dsn']

        with open(settings.BASE_DIR / 'api/event.schema.json', 'r') as f:
            schema = json.loads(f.read())

        for json_filename in options["json_files"]:
            with open(json_filename) as f:
                print("considering", json_filename)
                try:
                    data = json.loads(f.read())
                except Exception as e:
                    self.stderr.write("%s %s %s" % ("Not JSON", json_filename, str(e)))
                    continue

                if "event_id" not in data:
                    self.stderr.write("%s %s" % ("Probably not a (single) event", json_filename))
                    continue

                if "timestamp" not in data:
                    # weirdly enough a large numer of sentry test data don't actually have this required attribute set.
                    # thus, we set it to something arbitrary on the sending side rather than have our server be robust
                    # for it.
                    data["timestamp"] = 0

                if "platform" not in data:
                    # in a few cases this value isn't set either in the sentry test data but I'd rather ignore those...
                    # because 'platform' is such a valuable piece of info while getting a sense of the shape of the data
                    self.stderr.write("%s %s" % ("Platform not set", json_filename))
                    continue

                if data.get("type", "") == "transaction":
                    # kinda weird that this is in the "type" field rather than endpoint/envelope but who cares, that's
                    # where the info lives and we use it as an indicator to skip
                    self.stderr.write("%s %s" % ("We don't do transactions", json_filename))
                    continue

                if data.get('profile'):
                    # yet another case of undocumented behavior that I don't care about
                    # ../sentry-current/static/app/utils/profiling/profile/formats/node/trace.json
                    self.stderr.write("%s %s" % ("124", json_filename))
                    continue

                if data.get('message'):
                    # yet another case of undocumented behavior that I don't care about (top-level "message")
                    # ../glitchtip/events/test_data/py_hi_event.json
                    self.stderr.write("%s %s" % ("asdf", json_filename))
                    continue

                try:
                    jsonschema.validate(data, schema)
                except jsonschema.ValidationError as e:
                    self.stderr.write("%s %s %s" % ("still not ok at", repr(e), json_filename))
                    continue

                try:
                    response = requests.post(
                        get_store_url(dsn),
                        headers={
                            "X-Sentry-Auth": get_header_value(dsn),
                            "X-BugSink-DebugInfo": json_filename,
                        },
                        json=data,
                    )
                    response.raise_for_status()
                except Exception as e:
                    self.stderr.write("%s %s" % ("foo", e))
