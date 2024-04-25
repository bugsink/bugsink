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


def zlib_generator(input_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    z = zlib.decompressobj(wbits=wbits)

    while True:
        compressed_chunk = input_stream.read(chunk_size)
        if not compressed_chunk:
            break

        yield z.decompress(compressed_chunk)

    yield z.flush()


def brotli_generator(input_stream, chunk_size=DEFAULT_CHUNK_SIZE):
    decompressor = brotli.Decompressor()

    while True:
        compressed_chunk = input_stream.read(chunk_size)
        if not compressed_chunk:
            break

        yield decompressor.process(compressed_chunk)

    assert decompressor.is_finished()


class GeneratorReader:

    def __init__(self, generator):
        self.generator = generator
        self.unread = b""

    def read(self, size=None):
        if size is None:
            for chunk in self.generator:
                self.unread += chunk

            result = self.unread
            self.unread = b""
            return result

        while size > len(self.unread):
            try:
                chunk = next(self.generator)
                if chunk == b"":
                    break
                self.unread += chunk
            except StopIteration:
                break

        self.unread, result = self.unread[size:], self.unread[:size]
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
