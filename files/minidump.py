import io
import zipfile
import symbolic
from sentry_sdk_extensions import capture_or_log_exception

from bugsink.utils import assert_
from .models import FileMetadata


def get_single_object(archive):
    # our understanding: sentry-cli uploads single-object archives; we need to get the single object out of it...
    # ...but this does raise the question of why archives exist at all... hence the assert
    objects = list(archive.iter_objects())
    assert_(len(objects) == 1)
    return objects[0]


def build_cfi_map_from_minidump_bytes(minidump_bytes):
    process_state = symbolic.minidump.ProcessState.from_minidump_buffer(minidump_bytes)

    frame_info_map = symbolic.minidump.FrameInfoMap.new()

    for module in process_state.modules():
        if not module.debug_id:
            continue

        dashed_debug_id = symbolic.debuginfo.id_from_breakpad(module.debug_id)
        if FileMetadata.objects.filter(debug_id=dashed_debug_id, file_type="dbg").count() == 0:
            continue

        dif_bytes = FileMetadata.objects.get(debug_id=dashed_debug_id, file_type="dbg").file.data
        archive = symbolic.debuginfo.Archive.from_bytes(dif_bytes)

        debug_object = get_single_object(archive)

        cfi = symbolic.minidump.CfiCache.from_object(debug_object)
        frame_info_map.add(module.debug_id, cfi)

    return frame_info_map


def extract_dif_metadata(dif_bytes):
    try:
        archive = symbolic.debuginfo.Archive.from_bytes(dif_bytes)
        debug_object = get_single_object(archive)
        return {
            "kind": debug_object.kind,  # "dbg", "lib", "src"
            "code_id": debug_object.code_id,
            "debug_id": debug_object.debug_id,
            # "file_format": debug_object.file_format,  # "elf", "macho", "pe", "sourcebundle"
        }
    except Exception as e:
        raise  # TODO stabalize what we do later
        capture_or_log_exception(e)
        return {}


def extract_source_context(src_bytes, filename, center_line, context=5):

    # TODO the usual worries about zip bombs/memory usage apply here.
    with zipfile.ZipFile(io.BytesIO(src_bytes)) as zf:
        # sourcebundle entries use relative paths like "src/main.c" or so says ChatGPT
        candidates = [n for n in zf.namelist() if n.endswith(filename)]

        if not candidates:
            return [], None, []

        with zf.open(candidates[0]) as f:
            lines = f.read().decode("utf-8").splitlines()

        # Clamp line range to valid indices
        start = max(center_line - context - 1, 0)
        end = min(center_line + context, len(lines))

        pre_context = lines[start:center_line - 1]
        context_line = lines[center_line - 1] if 0 <= center_line - 1 < len(lines) else None
        post_context = lines[center_line:end]

        return pre_context, context_line, post_context


def _find_module_for_address(process_state, abs_addr: int):
    for m in process_state.modules():
        if m.addr and m.size and m.addr <= abs_addr < (m.addr + m.size):
            return m
    return None


def event_threads_for_process_state(process_state):
    threads = []
    for thread_index, symbolic_thread in enumerate(process_state.threads()):
        frames = []

        for symbolic_frame in symbolic_thread.frames():
            module = _find_module_for_address(process_state, symbolic_frame.instruction)

            frame = {"instruction_addr": f"0x{symbolic_frame.instruction:x}"}

            if module and module.debug_id:
                dashed_debug_id = symbolic.debuginfo.id_from_breakpad(module.debug_id)

                file_metadata = FileMetadata.objects.filter(debug_id=dashed_debug_id, file_type="dbg").first()
                if file_metadata:
                    dif_bytes = file_metadata.file.data

                    archive = symbolic.debuginfo.Archive.from_bytes(dif_bytes)

                    obj = get_single_object(archive)

                    symcache = obj.make_symcache()

                    rel = symbolic_frame.instruction - module.addr
                    infos = symcache.lookup(rel)
                    if infos:
                        # tentative understanding: lookup may give multiple results (e.g. inlined code). we just pick
                        # the first arbitrarily which is "good enough for a PoC until proven otherwise"
                        line_info = infos[0]

                        frame["function"] = line_info.function_name
                        if line_info.filename:
                            frame["filename"] = line_info.filename
                        frame["lineno"] = line_info.line

                        src_meta = FileMetadata.objects.filter(debug_id=dashed_debug_id, file_type="src").first()
                        if src_meta and line_info.filename and line_info.line:
                            frame["pre_context"], frame["context_line"], frame["post_context"] = extract_source_context(
                                src_meta.file.data, line_info.filename, line_info.line)

            frames.append(frame)

        threads.append({
            "id": symbolic_thread.thread_id,
            "crashed": thread_index == process_state.requesting_thread,
            "stacktrace": {"frames": frames},
        })

    return threads
