import json
import requests

from django.core.management.base import BaseCommand

from compat.dsn import get_store_url, get_header_value


class Command(BaseCommand):
    help = "..."

    def add_arguments(self, parser):
        parser.add_argument("--dsn")
        parser.add_argument("json_files", nargs="+")

    def handle(self, *args, **options):
        dsn = options['dsn']

        for json_filename in options["json_files"]:
            with open(json_filename) as f:
                print("HIER", json_filename)
                try:
                    data = json.loads(f.read())
                except Exception as e:
                    self.stderr.write("%s %s %s" % ("Not JSON", json_filename, str(e)))

                try:
                    response = requests.post(
                        get_store_url(dsn),
                        headers={"X-Sentry-Auth": get_header_value(dsn)},
                        json=data,
                    )
                    response.raise_for_status()
                except Exception as e:
                    self.stderr.write("%s %s" % ("foo", e))
