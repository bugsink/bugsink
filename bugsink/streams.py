import zlib
import io
import brotli

from bugsink.app_settings import get_settings


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

    # Peppered with assertions b/c the brotli package is ill-documented.

    decompressor = brotli.Decompressor()
    input_is_finished = False

    while not (decompressor.is_finished() and input_is_finished):
        if decompressor.can_accept_more_data():
            compressed_chunk = input_stream.read(chunk_size)
            if compressed_chunk:
                data = decompressor.process(compressed_chunk, output_buffer_limit=chunk_size)
                # assertion on data here? I'm not sure yet whether we actually hard-expect it. OK, you were ready to
                # accept input, and you got it. Does it mean you have output per se? In the limit (a single compressed
                # byte) one would say that the answer is "no".

            else:
                input_is_finished = True
                data = decompressor.process(b"", output_buffer_limit=chunk_size)  # b"": no input available, "drain"
                brotli_assert(
                    len(data) or decompressor.is_finished(),
                    "Draining done -> decompressor finished; if not, something's off")

        else:
            data = decompressor.process(b"", output_buffer_limit=chunk_size)  # b"" compressor cannot accept more input
            brotli_assert(
                len(data) > 0,
                "A brotli processor that cannot accept input _must_ be able to produce output or it would be stuck.")

        if data:
            yield data


class GeneratorReader:
    """Read from a generator (yielding bytes) as from a file-like object."""

    def __init__(self, generator):
        self.generator = generator
        self.buffer = bytearray()

    def read(self, size=None):
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


def content_encoding_reader(request):
    encoding = request.META.get("HTTP_CONTENT_ENCODING", "").lower()

    if encoding == "gzip":
        return GeneratorReader(zlib_generator(request, WBITS_PARAM_FOR_GZIP))

    if encoding == "deflate":
        return GeneratorReader(zlib_generator(request, WBITS_PARAM_FOR_DEFLATE))

    if encoding == "br":
        return GeneratorReader(brotli_generator(request))

    return request


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

        if isinstance(max_length, str):  # reusing this is a bit of a hack, but leads to readable code at usage
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

        if isinstance(max_length, str):  # reusing this is a bit of a hack, but leads to readable code at usage
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


class NullWriter:
    def write(self, data):
        pass

    def close(self):
        pass
