from sentry_sdk.hub import GLOBAL_HUB

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Quick and dirty command to just raise an exception and see it show up in Bugsink"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-release",
            action="store_true",
            help="Set the value of the sent release to None",
        )

    def handle(self, *args, **options):
        if options["no_release"]:
            # The sentry client "tries hard" to get the release from the environment (including git); I have found the
            # following to be a workable way to set the release to None
            GLOBAL_HUB.client.options['release'] = None

        try:
            self.raise_exception("Exception raised on purpose - 2")
        except Exception as e:
            # self.raise_exception("An 'accident' happened while handling the exception")
            self.raise_exception_from("We intentionally translated this into the exception", e)

    def raise_exception(self, s):
        raise Exception(s)

    def raise_exception_from(self, s, e):
        s = "foo"
        l = ["bar", 1, None, ["bar", 1, None]]
        d = {
            "foo": "bar",
            "baz": 1,
            "snu": None,
            "recurse": {
                "foo": "bar",
                "baz": 1,
                "snu": None,
            },
        }
        raise Exception(s) from e
