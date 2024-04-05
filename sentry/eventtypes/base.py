from django.utils.encoding import force_str

from sentry.utils.safe import get_path
from sentry.utils.strings import strip, truncatechars


class DefaultEvent:
    key = "default"

    def get_metadata(self, data):
        message = strip(
            get_path(data, "logentry", "message")
            or get_path(data, "logentry", "formatted")
        )

        if message:
            title = truncatechars(message.splitlines()[0], 100)
        else:
            title = "<unlabeled event>"

        return {"title": title}

    def get_title(self, metadata):
        return metadata.get("title") or "<untitled>"

    def get_location(self, data):
        return force_str(data.get("transaction") or "")
