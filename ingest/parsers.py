import json
import io

from bugsink.streams import MaxDataWriter


class ParseError(Exception):
    pass


class NewlineFinder:
    error_for_eof = None

    def process(self, output_stream, chunk):
        index = chunk.find(b"\n")
        if index != -1:
            part_of_result, remainder = chunk[:index], chunk[index + 1:]
            output_stream.write(part_of_result)
            return True, remainder

        output_stream.write(chunk)
        return False, b""


class LengthFinder:

    def __init__(self, length, error_for_eof):
        self.error_for_eof = error_for_eof
        self.length = length
        self.count = 0

    def process(self, output_stream, chunk):
        needed = self.length - self.count
        if needed <= len(chunk):
            part_of_result, remainder = chunk[:needed], chunk[needed:]
            output_stream.write(part_of_result)
            return True, remainder

        self.count += len(chunk)
        output_stream.write(chunk)
        return False, b""


def readuntil(input_stream, initial_chunk, finder, output_stream, chunk_size):
    chunk = initial_chunk
    done = False

    done, remainder = finder.process(output_stream, chunk)

    while not done:
        chunk = input_stream.read(chunk_size)

        if not chunk:
            if finder.error_for_eof is None:
                # eof is implicit success
                return b"", True

            raise ParseError(finder.error_for_eof)

        done, remainder = finder.process(output_stream, chunk)

    return remainder, False


class StreamingEnvelopeParser:
    """
    Parse "Envelope" data.
    See https://develop.sentry.dev/sdk/envelopes/

    This is a streaming parser. We're not radical about performance (no Rust) but given [1] the relative maximum sizes
    (envelope: 100MiB, event: 1MiB -- in other words: 99% bloat is possible) and [2] our goal of being robust even on
    second rate hardware, it seems prudent to not just load everything into memory.

    Don't take the existance of a Streaming Parser here to mean that there's an actual end-to-end streaming connection
    between the SDK and our server though (which would enable "low latency parsing" and "full hangup on-error"), because
    there may be many things in your stack preventing that:

    1. nginx may do request buffering (it's the default, and recommended for Gunicorn); so our work starts when the
       client is done sending.
    2. nginx will do connection-close buffering (unpreventable AFAICT) - https://forum.nginx.org/read.php?11,299875
       so attempts to notify the client to stop sending are prevented.
    3. if request-buffering is turned off, and the upstream server manages to send out its response and close the
       connection before the whole request is streamed to it, nginx will (sometimes?) respond with a 502 (which would
       prevent the useful response, e.g. a 429, from reaching the client). Nginx's reason:
       "writev() failed (104: Connection reset by peer) while sending request to upstream"
    4. if running uvicorn, Django's asgi stack will do request buffering - https://code.djangoproject.com/ticket/33699
    """

    def __init__(self, input_stream, chunk_size=1024):
        self.input_stream = input_stream
        self.chunk_size = chunk_size

        self.remainder = b""  # leftover from previous read chunk that's not handled by a parser yet
        self.at_eof = False

        self.envelope_headers = None

    def _parse_headers(self, empty_is_error=False, eof_after_header_is_error=True):
        """
        Quoted from https://develop.sentry.dev/sdk/envelopes/#headers at version 9c7f19f96562
        conversion to numbered list mine

        > ### Headers

        > Envelopes contain Headers in several places. Headers are JSON-encoded objects
        > (key-value mappings) that follow these rules:

        > 1. Always encoded in UTF-8
        > 2. Must be valid JSON
        > 3. Must be declared in a single line; no newlines
        > 4. Always followed by a newline (`\n`) or the end of the file
        > 5. Must not be padded by leading or trailing whitespace
        > 6. Should be serialized in their most compact form without additional white
        >    space. Whitespace within the JSON headers is permitted, though discouraged.
        > 7. Unknown attributes are allowed and should be retained by all implementations;
        >    however, attributes not covered in this spec must not be actively emitted by
        >    any implementation.
        > 8. All known headers and their data types can be validated by an implementation;
        >    if validation fails, the Envelope may be rejected as malformed.
        > 9. Empty headers `{}` are technically valid

        (Note that the combination of point 6 and the fact that JSON strings may not contain newlines unescaped makes
        the whole headers-terminated-by-newline possible)
        """

        header_stream = MaxDataWriter("MAX_HEADER_SIZE", io.BytesIO())

        # points 3, 4 (we don't use 5, 6, 7, 9 explicitly)
        self.remainder, self.at_eof = readuntil(
            self.input_stream, self.remainder, NewlineFinder(), header_stream, self.chunk_size)

        header_stream_value = header_stream.getvalue()
        if self.at_eof:
            if header_stream_value == b"":
                if empty_is_error:
                    raise ParseError("Expected headers, got EOF")

                return None

            if eof_after_header_is_error:
                # We found some header-data, but nothing else. This is an error
                raise ParseError("EOF when reading headers; what is this a header for then?")

        try:
            return json.loads(header_stream_value.decode("utf-8"))  # points 1, 2
        except json.JSONDecodeError as e:
            raise ParseError("Header not JSON") from e

    def get_envelope_headers(self):
        if self.envelope_headers is None:
            # see test_eof_after_envelope_headers for why we don't error on EOF-after-header here
            self.envelope_headers = self._parse_headers(empty_is_error=True, eof_after_header_is_error=False)

        return self.envelope_headers

    def get_items(self, output_stream_factory):
        # yields the item_headers and item_output_streams (with the content of the items written into them)
        # closing the item_output_stream is the responsibility of the calller

        self.get_envelope_headers()

        while not self.at_eof:
            item_headers = self._parse_headers(empty_is_error=False, eof_after_header_is_error=True)
            if item_headers is None:
                self.at_eof = True
                break

            if "length" in item_headers:
                length = item_headers["length"]
                finder = LengthFinder(length, error_for_eof="EOF while reading item with explicitly specified length")
            else:
                finder = NewlineFinder()

            item_output_stream = output_stream_factory(item_headers)
            self.remainder, self.at_eof = readuntil(
                self.input_stream, self.remainder, finder, item_output_stream, self.chunk_size)

            if "length" in item_headers:
                # items with an explicit length are terminated by a newline (if at EOF, this is optional as per the set
                # of examples in the docs)
                should_be_empty = io.BytesIO()
                self.remainder, self.at_eof = readuntil(
                    self.input_stream, self.remainder, NewlineFinder(), should_be_empty, self.chunk_size)
                if should_be_empty.getvalue() != b"":
                    raise ParseError("Item with explicit length not terminated by newline/EOF")

            yield item_headers, item_output_stream

    def get_items_directly(self):
        # this method is just convenience for testing

        for item_headers, output_stream in self.get_items(lambda item_headers: io.BytesIO()):
            yield item_headers, output_stream.getvalue()
