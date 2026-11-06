from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from .zip import open_zip_entry


class ZipEntryTests(TestCase):
    def test_read_compressed_entry_without_c_zlib(self):
        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("source.js", b"hello world")

        with ZipFile(bundle) as archive, patch("zipfile.zlib.decompressobj") as c_zlib:
            c_zlib.return_value.decompress.side_effect = AssertionError("C zlib must not decompress ZIP entries")
            with open_zip_entry(archive, "source.js") as stream:
                self.assertEqual(b"hello world", stream.read())
