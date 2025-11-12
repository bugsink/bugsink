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
    for thread_index, thread in enumerate(process_state.threads()):
        thread_frames = []

        for frame in thread.frames():
            module = _find_module_for_address(process_state, frame.instruction)
            fn = file = None
            line = 0

            if module and module.debug_id:
                dashed_debug_id = symbolic.debuginfo.id_from_breakpad(module.debug_id)

                file_metadata = FileMetadata.objects.filter(debug_id=dashed_debug_id, file_type="dbg").first()
                if file_metadata:
                    dif_bytes = file_metadata.file.data

                    archive = symbolic.debuginfo.Archive.from_bytes(dif_bytes)
                    objects = list(archive.iter_objects())
                    assert len(objects) == 1
                    obj = objects[0]

                    symcache = obj.make_symcache()

                    rel = frame.instruction - module.addr
                    infos = symcache.lookup(rel) or symcache.lookup(rel - 1)  # "or -1" from ChatGPT... should we do it?
                    if infos:
                        li = infos[0]
                        fn = li.function_name
                        file = li.filename
                        line = li.line

                        # if we have line info, try source bundle
                        src_meta = FileMetadata.objects.filter(debug_id=dashed_debug_id, file_type="src").first()
                        if src_meta and file and line:
                            src_bytes = src_meta.file.data
                            pre_ctx, ctx_line, post_ctx = extract_source_context(src_bytes, file, line)

            thread_frames.append({
                "instruction_addr": f"0x{frame.instruction:x}",
                "function": fn or "<unknown>",
                "filename": file,
                "lineno": line,
                "pre_context": pre_ctx,
                "context_line": ctx_line,
                "post_context": post_ctx,
            })

        threads.append({
            "id": thread.thread_id,
            "crashed": thread_index == process_state.requesting_thread,
            "stacktrace": {"frames": thread_frames},
        })

    return threads
