import codecs

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.utils import json


class EnvelopeParser(JSONParser):
    media_type = "application/x-sentry-envelope"

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parses the incoming bytestream as JSON and returns the resulting data.
        Supports multiple lines of JSON objects
        """
        parser_context = parser_context or {}
        encoding = parser_context.get("encoding", settings.DEFAULT_CHARSET)

        try:
            decoded_stream = codecs.getreader(encoding)(stream)
            parse_constant = json.strict_constant if self.strict else None
            messages = []
            for line in decoded_stream:
                messages.append(json.loads(line, parse_constant=parse_constant))
            return messages
        except ValueError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))
