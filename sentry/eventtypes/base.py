from sentry.utils.safe import get_path
from sentry.utils.strings import strip, truncatechars


class DefaultEvent:
    """The DefaultEvent is the Event for which there is no exception set. Given the implementation of `get_title`, I'd
    actually say that this is basically the LogMessageEvent.
    """

    def get_title(self, data):
        message = strip(
            get_path(data, "logentry", "message")
            or get_path(data, "logentry", "formatted")
        )

        if message:
            return truncatechars(message.splitlines()[0], 100)

        return "<unlabeled event>"
