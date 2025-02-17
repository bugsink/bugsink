import logging
from sentry_sdk.transport import HttpTransport


# the lazy choice: I've already got loggers set up for bugsink; I'll just use them. Better would be: just use "sentry"
logger = logging.getLogger("bugsink.sentry")


class MoreLoudlyFailingTransport(HttpTransport):
    def on_dropped_event(self, reason):
        # type: (str) -> None
        # ... do you thing ...
        print("Sentry SDK dropped event:", reason)
