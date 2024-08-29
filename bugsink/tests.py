import io
import brotli

from unittest import TestCase as RegularTestCase

from .volume_based_condition import VolumeBasedCondition
from .streams import (
    compress_with_zlib, GeneratorReader, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE, MaxDataReader,
    MaxDataWriter, zlib_generator, brotli_generator)
from .scripts.server_unified import ParentProcess


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
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10
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
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10
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
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10

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
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10
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


class ServerUnifiedTestCase(RegularTestCase):

    def test_arg_parsing(self):
        def _check(argv, expected_pre_start, expected_parallel):
            pre_start = ParentProcess.get_pre_start_command_args(argv)
            parallel = ParentProcess.get_parallel_command_args(argv)
            self.assertEqual(expected_pre_start, pre_start)
            self.assertEqual(expected_parallel, parallel)

        _check(
            # meaning: a single empty command (which would lead to a failure). It's the meaningless case anyway, so I'm
            # not going to make any special-case handling for it. In other words: there must be at least one command
            # (and even that is quite meaningless, since you could just run the command directly).
            ["script.py"],
            [],
            [[]],
        )

        _check(
            ["script.py", "a", "b"],
            [],
            [["a", "b"]],
        )

        _check(
            ["script.py", "a", "b", "UNIFIED_WITH", "c", "d", "UNIFIED_WITH", "e", "f"],
            [],
            [["a", "b"], ["c", "d"], ["e", "f"]],
        )

        _check(
            ["script.py", "a", "b", "AMP_AMP", "c", "d", "UNIFIED_WITH", "e", "f"],
            [["a", "b"]],
            [["c", "d"], ["e", "f"]],
        )

        _check(
            ["script.py", "a", "b", "UNIFIED_WITH", "c", "d", "UNIFIED_WITH", "e", "f"],
            [],
            [["a", "b"], ["c", "d"], ["e", "f"]],
        )

        _check(
            ["script.py", "a", "b", "AMP_AMP", "c", "d", "AMP_AMP", "e", "f"],
            [["a", "b"], ["c", "d"]],
            [["e", "f"]],
        )

        _check(
            ["script.py", "a", "b", "AMP_AMP", "c", "d", "AMP_AMP",
                "e", "f", "UNIFIED_WITH", "g", "h", "UNIFIED_WITH", "i", "j"],
            [["a", "b"], ["c", "d"]],
            [["e", "f"], ["g", "h"], ["i", "j"]],
        )
