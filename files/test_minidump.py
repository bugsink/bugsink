from hashlib import sha1
from io import BytesIO
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

import symbolic
from django.test import tag
from django.utils._os import safe_join

from bugsink.app_settings import override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project

from .minidump import (
    build_cfi_map_from_minidump_bytes, event_threads_for_process_state, extract_dif_kind, extract_source_context,
    parse_debug_object, read_source_lines,
)
from .models import File, FileMetadata
from .zip import open_zip_entry


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
        with ZipFile(BytesIO(bundle)) as zf:
            lines = read_source_lines(zf, "main.c")

        self.assertEqual((
            ["int main(void) {", "    int *value = NULL;", "    int result;", "", '    puts("Reading value");'],
            "    result = *value;",
            ['    printf("Value: %d", result);', "", '    puts("Done");', "    return 0;", "}"],
        ), extract_source_context(lines, 8))

    def test_source_at_size_limit_has_context(self):
        source = b"return 0;\n" * 100
        bundle = self.source_bundle(source)
        with override_settings(MAX_SOURCE_CONTEXT_FILE_SIZE=len(source)):
            with ZipFile(BytesIO(bundle)) as zf:
                lines = read_source_lines(zf, "main.c")
            self.assertEqual(([], "return 0;", []), extract_source_context(lines, 1, context=0))

    def test_oversized_source_has_no_context(self):
        source = b"return 0;\n" * 100
        bundle = self.source_bundle(source)
        self.assertLess(len(bundle), len(source) - 1)
        with override_settings(MAX_SOURCE_CONTEXT_FILE_SIZE=len(source) - 1):
            with ZipFile(BytesIO(bundle)) as zf:
                lines = read_source_lines(zf, "main.c")
            self.assertEqual(([], None, []), extract_source_context(lines, 1, context=0))


class MinidumpSymbolicationTests(TransactionTestCase):
    # LLM-generated; not deeply inspected, but they do seem to cover the main cases we care about.

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(name="test")
        self.main_debug_id = "0123456789ABCDEF0123456789ABCDEF0"
        self.worker_debug_id = "FEDCBA9876543210FEDCBA98765432100"

        self.store_file(self.main_debug_id, "dbg", b"""MODULE Linux x86_64 0123456789ABCDEF0123456789ABCDEF0 example
FILE 0 src/main.c
FUNC 10 10 0 main
10 10 6 0
FUNC 20 10 0 helper
20 10 2 0
""")
        self.store_file(self.worker_debug_id, "dbg", b"""MODULE Linux x86_64 FEDCBA9876543210FEDCBA98765432100 worker
FILE 0 src/worker.c
FUNC 10 10 0 worker
10 10 2 0
""")

        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("src/main.c", """int helper(void) {
    return 42;
}

int main(void) {
    return helper();
}
""")
        self.store_file(self.main_debug_id, "src", bundle.getvalue())

        bundle = BytesIO()
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("src/worker.c", """void worker(void) {
    do_work();
}
""")
        self.store_file(self.worker_debug_id, "src", bundle.getvalue())

        # Only the already-unwound threads/modules are stand-ins; symbol lookup and source extraction are real.
        self.process_state = SimpleNamespace(
            modules=lambda: [
                SimpleNamespace(addr=0x1000, size=0x100, debug_id=self.main_debug_id),
                SimpleNamespace(addr=0x2000, size=0x100, debug_id=self.worker_debug_id),
            ],
            threads=lambda: [
                SimpleNamespace(thread_id=101, frames=lambda: [
                    SimpleNamespace(instruction=0x2010),
                    SimpleNamespace(instruction=0x1020),
                    SimpleNamespace(instruction=0x1010),
                ]),
                SimpleNamespace(thread_id=202, frames=lambda: [
                    SimpleNamespace(instruction=0x1010),
                    SimpleNamespace(instruction=0x3000),
                ]),
            ],
            requesting_thread=0,
        )

    def store_file(self, debug_id, file_type, data):
        # usedforsecurity=False: SHA-1 matches the upload protocol; here it only identifies test files.
        file = File.objects.create(
            checksum=sha1(data, usedforsecurity=False).hexdigest(), filename=file_type, size=len(data), data=data)
        FileMetadata.objects.create(
            project=self.project, debug_id=symbolic.debuginfo.id_from_breakpad(debug_id),
            file_type=file_type, file=file)

    def test_symbolication_with_source_context(self):
        threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual([
            {"id": 101, "crashed": True, "stacktrace": {"frames": [
                {
                    "instruction_addr": "0x2010", "function": "worker", "filename": "worker.c", "lineno": 2,
                    "pre_context": ["void worker(void) {"], "context_line": "    do_work();", "post_context": ["}"],
                },
                {
                    "instruction_addr": "0x1020", "function": "helper", "filename": "main.c", "lineno": 2,
                    "pre_context": ["int helper(void) {"], "context_line": "    return 42;",
                    "post_context": ["}", "", "int main(void) {", "    return helper();", "}"],
                },
                {
                    "instruction_addr": "0x1010", "function": "main", "filename": "main.c", "lineno": 6,
                    "pre_context": ["int helper(void) {", "    return 42;", "}", "", "int main(void) {"],
                    "context_line": "    return helper();", "post_context": ["}"],
                },
            ]}},
            {"id": 202, "crashed": False, "stacktrace": {"frames": [
                {
                    "instruction_addr": "0x1010", "function": "main", "filename": "main.c", "lineno": 6,
                    "pre_context": ["int helper(void) {", "    return 42;", "}", "", "int main(void) {"],
                    "context_line": "    return helper();", "post_context": ["}"],
                },
                {"instruction_addr": "0x3000"},
            ]}},
        ], threads)

    def test_symbolication_without_debug_files(self):
        FileMetadata.objects.filter(file_type="dbg").delete()

        threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual([
            {"id": 101, "crashed": True, "stacktrace": {"frames": [
                {"instruction_addr": "0x2010"}, {"instruction_addr": "0x1020"}, {"instruction_addr": "0x1010"},
            ]}},
            {"id": 202, "crashed": False, "stacktrace": {"frames": [
                {"instruction_addr": "0x1010"}, {"instruction_addr": "0x3000"},
            ]}},
        ], threads)

    def test_symbolication_without_source_bundles(self):
        FileMetadata.objects.filter(file_type="src").delete()

        threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual([
            {"instruction_addr": "0x2010", "function": "worker", "filename": "worker.c", "lineno": 2},
            {"instruction_addr": "0x1020", "function": "helper", "filename": "main.c", "lineno": 2},
            {"instruction_addr": "0x1010", "function": "main", "filename": "main.c", "lineno": 6},
        ], threads[0]["stacktrace"]["frames"])

    def test_debug_file_is_parsed_once_for_frames_at_different_load_addresses(self):
        modules = list(self.process_state.modules())
        modules.append(SimpleNamespace(addr=0x4000, size=0x100, debug_id=self.main_debug_id))
        self.process_state.modules = lambda: modules
        self.process_state.threads = lambda: [SimpleNamespace(thread_id=101, frames=lambda: [
            SimpleNamespace(instruction=0x1010), SimpleNamespace(instruction=0x4020),
        ] * 100)]

        with patch("files.minidump.parse_debug_object", wraps=parse_debug_object) as parse:
            threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual(1, parse.call_count)
        self.assertEqual(["main", "helper"] * 100, [
            frame["function"] for frame in threads[0]["stacktrace"]["frames"]])

    def test_source_files_are_read_once_for_repeated_frames(self):
        with patch("files.minidump.open_zip_entry", wraps=open_zip_entry) as read_source:
            threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual(2, read_source.call_count)  # main.c and worker.c, regardless of the number of frames.
        self.assertEqual("    return helper();", threads[1]["stacktrace"]["frames"][0]["context_line"])

    def test_missing_debug_files_are_looked_up_together(self):
        FileMetadata.objects.all().delete()
        self.process_state.threads = lambda: [SimpleNamespace(thread_id=101, frames=lambda: [
            SimpleNamespace(instruction=0x1010), SimpleNamespace(instruction=0x2010),
        ] * 100)]

        # First look for debug files belonging to this project. For missing files, also look among older uploads
        # that have no project recorded, so those uploads keep working. These are two queries for all 200 frames
        # together; we must not repeat the searches for each frame.
        with self.assertNumQueries(2):
            threads = event_threads_for_process_state(self.process_state, self.project)

        self.assertEqual(
            [{"instruction_addr": "0x1010"}, {"instruction_addr": "0x2010"}] * 100,
            threads[0]["stacktrace"]["frames"])

    def test_cfi_is_prepared_once_for_repeated_modules(self):
        modules = list(self.process_state.modules()) * 100
        self.process_state.modules = lambda: modules

        with patch("files.minidump.symbolic.minidump.ProcessState.from_minidump_buffer",
                   return_value=self.process_state):
            with patch("files.minidump.parse_debug_object", wraps=parse_debug_object) as parse:
                build_cfi_map_from_minidump_bytes(b"", self.project)

        self.assertEqual(2, parse.call_count)

    @tag("samples")
    def test_debug_file_provides_unwind_information(self):
        # Enough unwind info for this sample's crash() to recover its caller from the stack pointer.
        debug_id = "7B7D1968FF0D47AE4366E9C3A7E1B6750"
        self.store_file(debug_id, "dbg", b"""MODULE Linux x86_64 7B7D1968FF0D47AE4366E9C3A7E1B6750 null_read_av
STACK CFI INIT 2170 8 .cfa: $rsp 8 + .ra: .cfa -8 + ^
""")
        filename = safe_join(os.getenv("SAMPLES_DIR", "../event-samples"), "minidumps", "linux_null_read_av.dmp")
        with open(filename, "rb") as f:
            minidump_bytes = f.read()

        frame_infos = build_cfi_map_from_minidump_bytes(minidump_bytes, self.project)
        process_state = symbolic.ProcessState.from_minidump_buffer(minidump_bytes, frame_infos=frame_infos)
        frames = list(process_state.get_thread(process_state.requesting_thread).frames())

        self.assertEqual(0x402170, frames[0].instruction)
        self.assertEqual(0x401fce, frames[1].instruction)
        self.assertEqual("cfi", frames[1].trust)  # Recovered using our debug file, not guessed by stack scanning.
