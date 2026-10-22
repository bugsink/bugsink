from collections import defaultdict
from uuid import UUID
import zipfile
import symbolic
from sentry_sdk_extensions import capture_or_log_exception

from bugsink.utils import assert_
from bugsink.streams import MaxDataReader, MaxLengthExceeded
from .models import get_file_metadata_for_debug_ids
from .zip import open_zip_entry


def parse_debug_object(dif_bytes):
    """Parse exactly one native debug object from bytes"""

    if dif_bytes.startswith(b"SYSB"):
        # we explicitly refuse source bundles here; this is security-critical. The reason is that source bundles can
        # contain highly compressed manifests that Symbolic decompresses and parses without a size limit, potentially
        # exhausting memory. Artifact uploads can label source bundles as "dbg", so we cannot trust the stored type.
        raise ValueError("Expected debug information, got a source bundle")

    archive = symbolic.debuginfo.Archive.from_bytes(dif_bytes)
    # our understanding: sentry-cli uploads single-object archives; we need to get the single object out of it...
    # ...but this does raise the question of why archives exist at all... hence the assert
    objects = list(archive.iter_objects())
    assert_(len(objects) == 1)
    return objects[0]


def build_cfi_map_from_minidump_bytes(minidump_bytes, project):
    process_state = symbolic.minidump.ProcessState.from_minidump_buffer(minidump_bytes)

    module_ids_by_debug_id = defaultdict(set)
    for module in process_state.modules():
        if module.debug_id:
            debug_id = UUID(symbolic.debuginfo.id_from_breakpad(module.debug_id))
            module_ids_by_debug_id[debug_id].add(module.debug_id)

    metadata = get_file_metadata_for_debug_ids(project, module_ids_by_debug_id, "dbg", defer_file_data=True)
    frame_info_map = symbolic.minidump.FrameInfoMap.new()
    for debug_id, module_ids in module_ids_by_debug_id.items():
        if debug_id not in metadata:
            continue

        # Memory-critical: reading a deferred file caches its contents on the model. Pop it here so those contents
        # can be released when the helper returns, rather than keeping every debug file loaded.
        _add_cfi_for_modules(frame_info_map, metadata.pop(debug_id).file, module_ids)

    return frame_info_map


def _add_cfi_for_modules(frame_info_map, file, module_ids):
    dif_bytes = file.get_raw_data()
    debug_object = parse_debug_object(dif_bytes)
    for module_id in module_ids:
        cfi = symbolic.minidump.CfiCache.from_object(debug_object)
        frame_info_map.add(module_id, cfi)


def extract_dif_kind(dif_bytes):
    if dif_bytes.startswith(b"SYSB"):
        # Source bundles are valid uploads, but parse_debug_object deliberately rejects them to protect against
        # unbounded manifest parsing in Symbolic. Classify them here without parsing the manifest.
        return "src"

    try:
        return parse_debug_object(dif_bytes).kind
    except Exception as e:
        raise  # TODO stabalize what we do later
        capture_or_log_exception(e)
        return None


def read_source_lines(zf, filename):
    # sourcebundle entries use relative paths like "src/main.c" or so says ChatGPT
    candidates = [n for n in zf.namelist() if n.endswith(filename)]

    if not candidates:
        return []

    with open_zip_entry(zf, candidates[0]) as f:
        try:
            source = MaxDataReader("MAX_SOURCE_CONTEXT_FILE_SIZE", f).read()
        except MaxLengthExceeded:
            # Omit context rather than fail on oversized sources. The default value of the setting
            # "should be enough" for typical source files so it's "not expected to happen" but if it does
            # we want to do it gracefully.
            return []
    return source.decode("utf-8").splitlines()


def extract_source_context(lines, center_line, context=5):
    # Clamp line range to valid indices
    start = max(center_line - context - 1, 0)
    end = min(center_line + context, len(lines))

    pre_context = lines[start:center_line - 1]
    context_line = lines[center_line - 1] if 0 <= center_line - 1 < len(lines) else None
    post_context = lines[center_line:end]

    return pre_context, context_line, post_context


def _find_module_for_address(modules, abs_addr: int):
    for m in modules:
        if m.addr and m.size and m.addr <= abs_addr < (m.addr + m.size):
            return m
    return None


def event_threads_for_process_state(process_state, project):
    modules = list(process_state.modules())
    debug_ids = {}
    frames_by_debug_id = defaultdict(list)
    threads = []
    for thread_index, symbolic_thread in enumerate(process_state.threads()):
        frames = []

        for symbolic_frame in symbolic_thread.frames():
            module = _find_module_for_address(modules, symbolic_frame.instruction)

            frame = {"instruction_addr": f"0x{symbolic_frame.instruction:x}"}

            if module and module.debug_id:
                if module.debug_id not in debug_ids:
                    debug_ids[module.debug_id] = UUID(symbolic.debuginfo.id_from_breakpad(module.debug_id))
                debug_id = debug_ids[module.debug_id]
                frames_by_debug_id[debug_id].append((frame, symbolic_frame.instruction - module.addr))

            frames.append(frame)

        threads.append({
            "id": symbolic_thread.thread_id,
            "crashed": thread_index == process_state.requesting_thread,
            "stacktrace": {"frames": frames},
        })

    metadata = get_file_metadata_for_debug_ids(project, frames_by_debug_id, "dbg", defer_file_data=True)
    source_frames_by_debug_id = {}
    for debug_id, frames in frames_by_debug_id.items():
        if debug_id not in metadata:
            continue

        # Memory-critical: reading a deferred file caches its contents on the model. Pop it here so those contents
        # can be released when the helper returns, rather than keeping every debug file loaded.
        frames_by_filename = _symbolicate_frames(metadata.pop(debug_id).file, frames)
        if frames_by_filename:
            source_frames_by_debug_id[debug_id] = frames_by_filename

    metadata = get_file_metadata_for_debug_ids(project, source_frames_by_debug_id, "src", defer_file_data=True)
    for debug_id, frames_by_filename in source_frames_by_debug_id.items():
        if debug_id not in metadata:
            continue

        # Drop this model too, so the full source bundle isn't retained after the helper returns.
        _add_source_context(metadata.pop(debug_id).file, frames_by_filename)

    return threads


def _symbolicate_frames(file, frames):
    dif_bytes = file.get_raw_data()
    obj = parse_debug_object(dif_bytes)
    symcache = obj.make_symcache()
    frames_by_filename = defaultdict(list)
    for frame, rel in frames:
        infos = symcache.lookup(rel)
        if infos:
            # tentative understanding: lookup may give multiple results (e.g. inlined code). we just pick
            # the first arbitrarily which is "good enough for a PoC until proven otherwise"
            line_info = infos[0]

            frame["function"] = line_info.function_name
            if line_info.filename:
                frame["filename"] = line_info.filename
            frame["lineno"] = line_info.line

            if line_info.filename and line_info.line:
                frames_by_filename[line_info.filename].append(frame)

    return frames_by_filename


def _add_source_context(file, frames_by_filename):
    with file.open_for_read() as f:
        with zipfile.ZipFile(f) as zf:
            for filename, frames in frames_by_filename.items():
                lines = read_source_lines(zf, filename)
                for frame in frames:
                    frame["pre_context"], frame["context_line"], frame["post_context"] = extract_source_context(
                        lines, frame["lineno"])
