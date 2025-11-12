# copied from:
# https://github.com/getsentry/sentry/blob/f0ac91f2ec6b45ad18e5eea6df72c5c72573e964/src/sentry/models/minidump.py#L53
# with (as it stands) minor modifications.

import symbolic
from files.minidump import build_cfi_map_from_minidump_bytes, event_threads_for_process_state


def merge_minidump_event(data, minidump_bytes):
    frame_info_map = build_cfi_map_from_minidump_bytes(minidump_bytes)
    process_state = symbolic.ProcessState.from_minidump_buffer(minidump_bytes, frame_infos=frame_info_map)

    data['level'] = 'fatal' if process_state.crashed else 'info'

    exception_value = 'Assertion Error: %s' % process_state.assertion if process_state.assertion \
        else 'Fatal Error: %s' % process_state.crash_reason
    # NO_BANANA: data['message'] is not the right target
    # data['message'] = exception_value

    if process_state.timestamp:
        data['timestamp'] = float(process_state.timestamp)

    # Extract as much system information as we can. TODO: We should create
    # a custom context and implement a specific minidump view in the event
    # UI.
    info = process_state.system_info
    context = data.setdefault('contexts', {})
    os = context.setdefault('os', {})
    device = context.setdefault('device', {})
    os['name'] = info.os_name
    os['version'] = info.os_version
    device['arch'] = info.cpu_family

    threads = event_threads_for_process_state(process_state)
    data.setdefault("threads", {})["values"] = threads

    # Mark the crashed thread and add its stacktrace to the exception
    crashed_thread = threads[process_state.requesting_thread]
    crashed_thread['crashed'] = True

    # Extract the crash reason and infos
    exception = {
        'value': exception_value,
        'thread_id': crashed_thread['id'],
        'type': process_state.crash_reason,
        # Move stacktrace here from crashed_thread (mutating!)
        'stacktrace': crashed_thread.pop('stacktrace'),
    }

    for frame in exception['stacktrace']['frames']:
        frame['in_app'] = True  # minidumps don't distinguish in_app frames; assume all are in_app

    exception['stacktrace']['frames'].reverse()  # "Frames should be sorted from oldest to newest."
    # TODO we don't have display-info for threads yet, I think?
    # we may need to revert the per-thread stacktraces above as well then

    data.setdefault('exception', {}) \
        .setdefault('values', []) \
        .append(exception)

    # Extract referenced (not all loaded) images
    images = [{
        'type': 'elf',                    # TODO not sure what this should _actually_ be
        'image_addr': module.addr,
        'image_size': module.size,
        'code_file': module.code_file,
        'code_id': module.code_id,
        'debug_file': module.debug_file,
        'debug_id': symbolic.debuginfo.id_from_breakpad(module.debug_id) if module.debug_id else None,
    } for module in process_state.modules()]

    data.setdefault('debug_meta', {})['images'] = images
