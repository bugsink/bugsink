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
        from sentry_sdk import set_tag
        set_tag("foo", "bar")
        set_tag("baz", "1")

        a = b = c = d = ee = f = g = h = i = j = 0  # noqa (unused in code, simply 10 variables to check MAX_DATABAG_*)

        if options["no_release"]:
            # The sentry client "tries hard" to get the release from the environment (including git); I have found the
            # following to be a workable way to set the release to None. (But I have checked that, in the absence of
            # .git, the release is set to None by default by the Python sentry sdk.)
            GLOBAL_HUB.client.options['release'] = None

        """
        RTFM: github issue (doesn't work though)

        # import sys
        import logging
        log = logging.getLogger(__name__)
        # sys.exc_clear()  doesn't exist in Python 3
        log.error("As done on the GitHub issue", exc_info=True)  <= doesn't actually do anything though

        """

        # GitHub 2nd attempt
        # > The logging integrations is a default integration so it will be enabled automatically when you initialize
        # > the Sentry SDK.

        """
        plain logging.error
        import logging
        logger = logging.getLogger(__name__)
        logger.error("I am an error message - using logging.error")
        """

        """
        import sentry_sdk
        sentry_sdk.capture_message("Unexpected event", level="warning", stack_trace=True)
        """

        """
        # my solution:
        # from sentry_sdk_extensions import capture_stacktrace
        # capture_stacktrace("I have been captured")
        """

    def raise_exception(self, msg):
        raise ValueError(msg)

    def raise_exception_from(self, msg, e):
        s = "foo"  # noqa unused variable, but we want to test that it shows up in the local variables in Bugsink
        l = ["bar", 1, None, ["bar", 1, None]] # noqa
        d = {  # noqa
            "foo": "bar",
            "baz": 1,
            "snu": None,
            "recurse": {
                "foo": "bar",
                "baz": 1,
                "snu": None,
            },
        }
        raise ValueError(msg) from e
