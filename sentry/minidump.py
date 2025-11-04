# copied from:
# https://github.com/getsentry/sentry/blob/f0ac91f2ec6b45ad18e5eea6df72c5c72573e964/src/sentry/models/minidump.py#L53
# with (as it stands) minor modifications.

import logging
from symbolic import ProcessState


def merge_minidump_event(data, minidump_bytes):
    state = ProcessState.from_minidump_buffer(minidump_bytes)

    data['level'] = 'fatal' if state.crashed else 'info'

    exception_value =  'Assertion Error: %s' % state.assertion if state.assertion \
        else 'Fatal Error: %s' % state.crash_reason
    # NO_BANANA: data['message'] is not the right target
    # data['message'] = exception_value

    if state.timestamp:
        data['timestamp'] = float(state.timestamp)

    # Extract as much system information as we can. TODO: We should create
    # a custom context and implement a specific minidump view in the event
    # UI.
    info = state.system_info
    context = data.setdefault('contexts', {})
    os = context.setdefault('os', {})
    device = context.setdefault('device', {})
    os['name'] = info.os_name
    os['version'] = info.os_version
    device['arch'] = info.cpu_family

    # We can extract stack traces here already but since CFI is not
    # available yet (without debug symbols), the stackwalker will
    # resort to stack scanning which yields low-quality results. If
    # the user provides us with debug symbols, we will reprocess this
    # minidump and add improved stacktraces later.
    threads = [{
        'id': thread.thread_id,
        'crashed': False,
        'stacktrace': {
            'frames': [{
                'instruction_addr': '0x%x' % frame.instruction,
                'function': '<unknown>',  # Required by interface
            } for frame in thread.frames()],
        },
    } for thread in state.threads()]
    data.setdefault('threads', {})['values'] = threads

    # Mark the crashed thread and add its stacktrace to the exception
    crashed_thread = threads[state.requesting_thread]
    crashed_thread['crashed'] = True

    # Extract the crash reason and infos
    exception = {
        'value': exception_value,
        'thread_id': crashed_thread['id'],
        'type': state.crash_reason,
        # Move stacktrace here from crashed_thread (mutating!)
        'stacktrace': crashed_thread.pop('stacktrace'),
    }

    data.setdefault('exception', {}) \
        .setdefault('values', []) \
        .append(exception)

    # Extract referenced (not all loaded) images
    images = [{
        'type': 'apple',  # Required by interface
        # 'uuid': module.uuid, NO_BANANA
        'image_addr': module.addr,
        'image_size': module.size,
        # 'name': module.name, NO_BANANA
    } for module in state.modules()]
    data.setdefault('debug_meta', {})['images'] = images
