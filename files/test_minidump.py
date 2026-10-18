from io import BytesIO
from unittest import TestCase
from zipfile import ZipFile, ZIP_DEFLATED

from bugsink.app_settings import override_settings

from .minidump import extract_source_context


class SourceContextTests(TestCase):
    def source_bundle(self, source):
        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("src/main.c", source)
        return bundle.getvalue()

    def test_source_at_size_limit_has_context(self):
        source = b"return 0;\n" * 100
        bundle = self.source_bundle(source)
        with override_settings(MAX_SOURCE_CONTEXT_FILE_SIZE=len(source)):
            self.assertEqual(([], "return 0;", []), extract_source_context(bundle, "main.c", 1, context=0))

    def test_oversized_source_has_no_context(self):
        source = b"return 0;\n" * 100
        bundle = self.source_bundle(source)
        self.assertLess(len(bundle), len(source) - 1)
        with override_settings(MAX_SOURCE_CONTEXT_FILE_SIZE=len(source) - 1):
            self.assertEqual(([], None, []), extract_source_context(bundle, "main.c", 1, context=0))
