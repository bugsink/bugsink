from django.core.exceptions import BadRequest

import zlib
import io
import brotli

from bugsink.app_settings import get_settings
from bugsink.utils import assert_


DEFAULT_CHUNK_SIZE = 8 * 1024

# https://docs.python.org/3/library/zlib.html#zlib.decompress
# > +24 to +31 = 16 + (8 to 15): Uses the low 4 bits of the value as the window size logarithm. The input must include a
# > gzip header and trailer.
WBITS_PARAM_FOR_GZIP = 16 + zlib.MAX_WBITS  # zlib.MAX_WBITS == 15

# "deflate" simply means: the same algorithm as used for "gzip", but without the gzip header.
# https://docs.python.org/3/library/zlib.html#zlib.decompress
# > 8 to −15: Uses the absolute value of wbits as the window size logarithm. The input must be a raw stream with no
# > header or trailer.
WBITS_PARAM_FOR_DEFLATE = -zlib.MAX_WBITS


class MaxLengthExceeded(ValueError):
    pass


class BrotliError(ValueError):
    """similar to brotli.error, but separate from it, to clarify non-library failure"""


def brotli_assert(condition, message):
    if not condition:
        raise BrotliError(message)


def zlib_generator(input_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    z = zlib.decompressobj(wbits=wbits)

    while True:
        compressed_chunk = input_stream.read(chunk_size)
        if not compressed_chunk:
            break

        yield z.decompress(compressed_chunk)

    yield z.flush()


def brotli_generator(input_stream, chunk_size=DEFAULT_CHUNK_SIZE):
    # implementation notes: in principle chunk_size for input and output could be different, we keep them the same here.
    # I've also seen that the actual output data may be quite a bit larger than the output_buffer_limit; a detail that
    # I do not fully understand (but I understand that at least it's not _unboundedly_ larger).

    # The brotli_assertions in the below are designed to guarantee that progress towards termination is made. In short:
    # when no progress is made on the input_stream, either progress must be made on the output_stream or we must be in
    # finished state.
    decompressor = brotli.Decompressor()
    input_is_finished = False

    while not (decompressor.is_finished() and input_is_finished):
        if decompressor.can_accept_more_data():
            compressed_chunk = input_stream.read(chunk_size)
            if compressed_chunk:
                data = decompressor.process(compressed_chunk, output_buffer_limit=chunk_size)
                # brotli_assert not needed: we made progress on the `input_stream` in any case (we cannot infinitely be
                # in this branch because the input_stream is finite).

            else:
                input_is_finished = True
                data = decompressor.process(b"", output_buffer_limit=chunk_size)  # b"": no input available, "drain"
                brotli_assert(
                    len(data) or decompressor.is_finished(),
                    "'Draining done' should imply 'decompressor finished'; if not, something's off")

        else:
            data = decompressor.process(b"", output_buffer_limit=chunk_size)  # b"" compressor cannot accept more input
            brotli_assert(
                len(data) > 0,
                "A brotli processor that cannot accept input _must_ be able to produce output or it would be stuck.")

        if data:
            yield data


class GeneratorReader:
    """Read from a generator (yielding bytes) as from a file-like object. In practice: used by content_encoding_reader,
    so it's grown to fit that use case (and we may later want to reflect that in the name)."""

    readable = lambda self: True
    writable = lambda self: False
    seekable = lambda self: False

    def __init__(self, generator, bad_request_exceptions=()):
        self.generator = generator
        self.bad_request_exceptions = bad_request_exceptions
        self.buffer = bytearray()
        self.closed = False

    def read(self, size=None):
        try:
            return self._read(size)
        except self.bad_request_exceptions as e:
            raise BadRequest(str(e)) from e

    def _read(self, size=None):
        if size is None:
            for chunk in self.generator:
                self.buffer.extend(chunk)
            result = bytes(self.buffer)
            self.buffer.clear()
            return result

        while len(self.buffer) < size:
            try:
                chunk = next(self.generator)
                if not chunk:
                    break
                self.buffer.extend(chunk)
            except StopIteration:
                break

        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def readline(self, size=-1):
        newline_index = self.buffer.find(b"\n")
        while newline_index == -1:
            chunk = self.read(DEFAULT_CHUNK_SIZE)
            if not chunk:
                break
            self.buffer.extend(chunk)
            newline_index = self.buffer.find(b"\n")

        if newline_index != -1:
            end = newline_index + 1
        else:
            end = len(self.buffer)

        if size >= 0:
            end = min(end, size)

        result = bytes(self.buffer[:end])
        del self.buffer[:end]
        return result

    def flush(self):
        pass  # no-op for interface compatibility

    def close(self):
        # no-op for interface compatibility
        self.closed = True


def content_encoding_reader(request):
    encoding = request.META.get("HTTP_CONTENT_ENCODING", "").lower()
    if encoding == "gzip":
        return GeneratorReader(
            zlib_generator(request._stream, WBITS_PARAM_FOR_GZIP),
            bad_request_exceptions=(zlib.error,),
        )

    if encoding == "deflate":
        return GeneratorReader(
            zlib_generator(request._stream, WBITS_PARAM_FOR_DEFLATE),
            bad_request_exceptions=(zlib.error,)
        )

    if encoding == "br":
        return GeneratorReader(
            brotli_generator(request._stream),
            bad_request_exceptions=(brotli.error, BrotliError)
        )

    return request


def handle_request_content_encoding(request, max_length):
    """Turns a request w/ Content-Encoding into an unpacked equivalent; for further "regular" (POST, FILES) handling
    by Django.
    """

    encoding = request.META.get("HTTP_CONTENT_ENCODING", "").lower()
    if encoding in ["gzip", "deflate", "br"]:
        assert_(not request._read_started)
        request._stream = MaxDataReader(max_length, content_encoding_reader(request))

        request.META["CONTENT_LENGTH"] = str(pow(2, 32) - 1)  # large enough (we can't predict the decompressed value)
        request.META.pop("HTTP_CONTENT_ENCODING")  # the resulting request is no longer encoded


def compress_with_zlib(input_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    # mostly useful for testing (compress-decompress cycles)

    output_stream = io.BytesIO()
    z = zlib.compressobj(wbits=wbits)

    while True:
        uncompressed_chunk = input_stream.read(chunk_size)
        if not uncompressed_chunk:
            break

        output_stream.write(z.compress(uncompressed_chunk))

    output_stream.write(z.flush())
    return output_stream.getvalue()


class MaxDataReader:

    def __init__(self, max_length, stream):
        self.bytes_read = 0
        self.stream = stream

        if isinstance(max_length, str):  # support for settings-name max_length makes both the code and errors better
            self.max_length = get_settings()[max_length]
            self.reason = "%s: %s" % (max_length, self.max_length)
        else:
            self.max_length = max_length
            self.reason = str(max_length)

    def read(self, size=None):
        if size is None:
            return self.read(self.max_length - self.bytes_read + 1)  # +1 to trigger the max length check

        result = self.stream.read(size)
        self.bytes_read += len(result)

        if self.bytes_read > self.max_length:
            raise MaxLengthExceeded("Max length (%s) exceeded" % self.reason)

        return result

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


class MaxDataWriter:

    def __init__(self, max_length, stream):
        self.bytes_written = 0
        self.stream = stream

        if isinstance(max_length, str):  # support for settings-name max_length makes both the code and errors better
            self.max_length = get_settings()[max_length]
            self.reason = "%s: %s" % (max_length, self.max_length)
        else:
            self.max_length = max_length
            self.reason = str(max_length)

    def write(self, data):
        self.bytes_written += len(data)

        if self.bytes_written > self.max_length:
            raise MaxLengthExceeded("Max length (%s) exceeded" % self.reason)

        self.stream.write(data)

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


class Writer:
    writable = lambda self: True
    readable = lambda self: False
    seekable = lambda self: False


class BrotliStreamWriter(Writer):
    def __init__(self, stream, quality, chunk_size=DEFAULT_CHUNK_SIZE):
        self.stream = stream
        self.compressor = brotli.Compressor(quality=quality)
        self.chunk_size = chunk_size
        self.closed = False

    def write(self, data):
        out = self.compressor.process(data)
        if out:
            self.stream.write(out)

    def flush(self):
        out = self.compressor.finish()
        if out:
            self.stream.write(out)

    def close(self):
        if self.closed:
            return
        try:
            self.flush()
        finally:
            self.closed = True


class ZlibStreamWriter(Writer):
    def __init__(self, stream, level, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
        self.stream = stream
        self.compressor = zlib.compressobj(level=level, wbits=wbits)
        self.chunk_size = chunk_size
        self.closed = False

    def write(self, data):
        out = self.compressor.compress(data)
        if out:
            self.stream.write(out)

    def flush(self):
        pass

    def close(self):
        if self.closed:
            return

        try:
            out = self.compressor.flush()
            if out:
                self.stream.write(out)
        finally:
            self.closed = True


class NullWriter:
    def write(self, data):
        pass

    def close(self):
        pass


class UnclosableBytesIO(io.BytesIO):
    """Intentionally does nothing on-close: BytesIO normally discards its buffer on .close(), breaking .getvalue(); this
    overrides it so that we can use it in code that usually deals with real files (and calls .close()) while still using
    the in-memory data afterwards. We just rely on the garbage collector for the actual cleanup."""

    def close(self):
        pass
