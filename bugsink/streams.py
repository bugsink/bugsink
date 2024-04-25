import zlib
import io


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


def zlib_generator(input_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    z = zlib.decompressobj(wbits=wbits)

    while True:
        compressed_chunk = input_stream.read(chunk_size)
        if not compressed_chunk:
            break

        yield z.decompress(compressed_chunk)

    yield z.flush()


class ZLibReader:

    def __init__(self, input_stream, wbits):
        self.generator = zlib_generator(input_stream, wbits)
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
        return ZLibReader(request, WBITS_PARAM_FOR_GZIP)

    if encoding == "deflate":
        return ZLibReader(request, WBITS_PARAM_FOR_DEFLATE)

    if encoding == "br":
        raise NotImplementedError("Brotli not supported (yet)")

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

    def __init__(self, stream, max_length):
        self.bytes_read = 0
        self.stream = stream
        self.max_length = max_length

    def read(self, size=None):
        if size is None:
            return self.read(self.max_length - self.bytes_read + 1)  # +1 to trigger the max length check

        result = self.stream.read(size)
        self.bytes_read += len(result)

        if self.bytes_read > self.max_length:
            raise ValueError("Max length (%s) exceeded" % self.max_length)

        return result


class MaxDataWriter:

    def __init__(self, stream, max_length):
        self.bytes_written = 0
        self.stream = stream
        self.max_length = max_length

    def write(self, data):
        self.bytes_written += len(data)

        if self.bytes_written > self.max_length:
            raise ValueError("Max length exceeded")

        self.stream.write(data)
