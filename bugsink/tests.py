import io
import brotli

from unittest import TestCase as RegularTestCase

from .volume_based_condition import VolumeBasedCondition
from .streams import (
    compress_with_zlib, GeneratorReader, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE, MaxDataReader,
    MaxDataWriter, zlib_generator, brotli_generator)


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


class VolumeBasedConditionTestCase(RegularTestCase):

    def test_serialization(self):
        vbc = VolumeBasedCondition("day", 1, 100)
        self.assertEqual({"period": "day", "nr_of_periods": 1, "volume": 100}, vbc.to_dict())

        vbc2 = VolumeBasedCondition.from_dict(vbc.to_dict())
        self.assertEqual(vbc, vbc2)


class StreamsTestCase(RegularTestCase):

    def test_compress_decompress_gzip(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_GZIP))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_GZIP))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_deflate(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_brotli(self):
        myself_times_ten = open(__file__, 'rb').read() * 10

        compressed_stream = io.BytesIO(brotli.compress(myself_times_ten))

        result = b""
        reader = GeneratorReader(brotli_generator(compressed_stream))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_read_none(self):
        myself_times_ten = open(__file__, 'rb').read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        result = reader.read(None)
        self.assertEqual(myself_times_ten, result)

    def test_max_data_reader(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        for i in range(25):
            self.assertEqual(b"hellohello", reader.read(10))

        with self.assertRaises(ValueError) as e:
            reader.read(10)

        self.assertEqual("Max length (250) exceeded", str(e.exception))

    def test_max_data_reader_none_ok(self):
        stream = io.BytesIO(b"hello" * 10)
        reader = MaxDataReader(250, stream)

        self.assertEqual(b"hello" * 10, reader.read(None))

    def test_max_data_reader_none_fail(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        with self.assertRaises(ValueError) as e:
            reader.read(None)

        self.assertEqual("Max length (250) exceeded", str(e.exception))

    def test_max_data_writer(self):
        stream = io.BytesIO()
        writer = MaxDataWriter(250, stream)

        for i in range(25):
            writer.write(b"hellohello")

        with self.assertRaises(ValueError):
            writer.write(b"hellohello")
