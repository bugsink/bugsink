import io


class ParseError(Exception):
    pass


class NewlineFinder:

    def __init__(self, error_for_eof):
        self.error_for_eof = error_for_eof

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
        if needed < len(chunk):
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

    def __init__(self, input_stream, chunk_size=1024):
        self.input_stream = input_stream
        self.chunk_size = chunk_size
        self.bufs = []
        self.at_eof = False

        self.envelope_headers = None

    def _parse_envelope_headers(self):
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
        """

        envelope_header_stream = io.BytesIO()
        header_bytes, self.at_eof = readuntil(
            self.input_stream, b"", NewlineFinder(error_for_eof=None), envelope_header_stream, self.chunk_size)

        # HIER GEBLEVEN: nu punt 1..9 implementeren voor deze header bytes
        # EN DAN: get_items

    def get_envelope_headers(self):
        if self.headers is None:
            self._parse_envelope_headers()
        return self.headers

    def get_items(self):
        # yields tuples of (item_header, item)

        # this parses the headers if it's not done yet, such that our 'seek pointer' is correct.
        self.get_envelope_headers()
