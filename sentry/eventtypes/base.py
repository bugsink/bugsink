from django.utils.encoding import force_str

from sentry.culprit import generate_culprit
from sentry.utils.safe import get_path
from sentry.utils.strings import strip, truncatechars


class BaseEvent:
    id = None

    def get_metadata(self, data):
        raise NotImplementedError

    def get_title(self, metadata):
        raise NotImplementedError

    def get_location(self, data):
        return None


class DefaultEvent(BaseEvent):
    key = "default"

    def get_metadata(self, data):
        message = strip(
            get_path(data, "logentry", "formatted")
            or get_path(data, "logentry", "message")
            or get_path(data, "message", "formatted")
            or get_path(data, "message")
        )

        if message:
            title = truncatechars(message.splitlines()[0], 100)
        else:
            title = "<unlabeled event>"

        return {"title": title}

    def get_title(self, metadata):
        return metadata.get("title") or "<untitled>"

    def get_location(self, data):
        return force_str(
            data.get("culprit")
            or data.get("transaction")
            or generate_culprit(data)
            or ""
        )
