from io import BytesIO
from unittest import TestCase
from zipfile import ZipFile, ZIP_DEFLATED

from bugsink.app_settings import override_settings

from .minidump import extract_dif_kind, extract_source_context, parse_debug_object


class DifKindTests(TestCase):
    def test_source_bundle_kind_does_not_require_manifest(self):
        self.assertEqual("src", extract_dif_kind(b"SYSB\x02\x00\x00\x00"))

    def test_breakpad_debug_file_kind(self):
        debug_file = b"MODULE Linux x86_64 0123456789ABCDEF0123456789ABCDEF0 example\n"
        self.assertEqual("dbg", extract_dif_kind(debug_file))

    def test_source_bundle_cannot_be_used_as_debug_file(self):
        with self.assertRaisesRegex(ValueError, "Expected debug information, got a source bundle"):
            parse_debug_object(b"SYSB\x02\x00\x00\x00")


class SourceContextTests(TestCase):
    def source_bundle(self, source):
        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("src/main.c", source)
        return bundle.getvalue()

    def test_source_context(self):
        source = b"""#include <stdio.h>

int main(void) {
    int *value = NULL;
    int result;

    puts("Reading value");
    result = *value;
    printf("Value: %d", result);

    puts("Done");
    return 0;
}

// End of program.
"""
        bundle = self.source_bundle(source)

        self.assertEqual((
            ["int main(void) {", "    int *value = NULL;", "    int result;", "", '    puts("Reading value");'],
            "    result = *value;",
            ['    printf("Value: %d", result);', "", '    puts("Done");', "    return 0;", "}"],
        ), extract_source_context(bundle, "main.c", 8))

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
