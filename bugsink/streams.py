import zlib


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


def decompress_with_zlib(input_stream, output_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    z = zlib.decompressobj(wbits=wbits)

    while True:
        compressed_chunk = input_stream.read(chunk_size)
        if not compressed_chunk:
            break

        output_stream.write(z.decompress(compressed_chunk))

    output_stream.write(z.flush())


def compress_with_zlib(input_stream, output_stream, wbits, chunk_size=DEFAULT_CHUNK_SIZE):
    # mostly useful for testing (compress-decompress cycles)
    z = zlib.compressobj(wbits=wbits)

    while True:
        uncompressed_chunk = input_stream.read(chunk_size)
        if not uncompressed_chunk:
            break

        output_stream.write(z.compress(uncompressed_chunk))

    output_stream.write(z.flush())


class MaxDataReader:

    def __init__(self, stream, max_length):
        self.bytes_read = 0
        self.stream = stream
        self.max_length = max_length

    def read(self, size=None):
        if size is None:
            raise ValueError("MaxDataReader.read() - size must be specified")

        # Note: we raise the error when an attempt is made to read to much data. In theory/principle this means that we
        # could be too strict, because we would complain before the actual problem had occurred, and the downstream read
        # may actually return something much smaller than what we request.
        # In practice [1] this is a rounding error [2] max sizes are usually integer multiples of our chunk size.
        # (this tool is meant to be used in some chunked setting)
        self.bytes_read += size

        if self.bytes_read > self.max_length:
            raise ValueError("Max length exceeded")

        return self.stream.read(size)


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
