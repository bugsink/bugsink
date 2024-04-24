
class ParseError(Exception):
    pass


class NewlineFinder:

    def __init__(self):
        self.indexof = -1

    def is_done_after(self, chunk):
        self.indexof = chunk.indexof(b"\n")
        return self.indexof != -1

    def result_and_remainder(self, bufs):
        last_buf_result, remainder = bufs[-1][:self.indexof], bufs[-1][self.indexof:]
        result = b"".join(bufs[:-1]) + last_buf_result
        return result, remainder

    def eof_result(self, bufs):
        return b"".join(bufs), b""


def readuntil(bufs, stream, finder, chunk_size, error_for_eof):
    # returns (finder_result, at_eof)
    # bufs is modified in place

    def readchunk():
        chunk = stream.read(chunk_size)
        if not chunk:
            if error_for_eof is None:
                # eof is implicit success
                return finder.eof_result(bufs), True

            raise ParseError(error_for_eof)
        bufs.append(chunk)
        return chunk

    # HIER NO WE NEED TO CHECK bufs FIRST!
    # (at least on entry)
    # this is a good reason to not do this as a list, but have a single buf
    chunk = readchunk()
    while not finder.is_done_after(chunk):
        chunk = readchunk()

    result, remainder = finder.result_and_remainder(bufs)

    bufs.clear()
    bufs.append(remainder)

    return result, False


class StreamingEnvelopeParser:

    def __init__(self, stream, chunk_size=1024):
        self.stream = stream
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

        header_bytes, self.at_eof = readuntil(self.bufs, self.stream, NewlineFinder(), self.chunk_size, error_for_eof=None)

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


