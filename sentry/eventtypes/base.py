from sentry.utils.safe import get_path
from sentry.utils.strings import strip, truncatechars


class DefaultEvent:

    def get_title(self, data):
        message = strip(
            get_path(data, "logentry", "message")
            or get_path(data, "logentry", "formatted")
        )

        if message:
            return truncatechars(message.splitlines()[0], 100)
        return "<unlabeled event>"
