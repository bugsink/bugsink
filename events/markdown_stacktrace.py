# This module is almost entirely written by a chatbot, with heavy guidance in terms of desired outcome, but very little
# code review. It's smoke-tested against all sample events and char-for-char tested for a single representative event.
#
# Large parts mirror (have stolen from) existing stacktrace-rendering logic from our views/templates, trimmed down for a
# Markdown/LLM audience.
#
# Purpose: expose event stacktraces (frames, source, locals) as clean, low-maintenance text for humans and machine
# tools. As in the UI: focus on the stacktrace rather than the event metadata.
#
# The provided markdown is not a stable interface; it's intended to be useful but not something you'd parse
# programmatically (just use the event data instead).

import logging
from django.conf import settings
from events.utils import apply_sourcemaps

from sentry_sdk_extensions import capture_or_log_exception

logger = logging.getLogger("bugsink.issues")


def _code_segments(frame):
    pre = frame.get("pre_context") or []
    ctx = frame.get("context_line")
    post = frame.get("post_context") or []

    pre = [("" if l is None else str(l)) for l in pre]
    post = [("" if l is None else str(l)) for l in post]
    if ctx is not None:
        ctx = str(ctx)

    return pre, ctx, post


def _code_lines(frame):
    pre, ctx, post = _code_segments(frame)
    lines = []
    lines.extend(pre)
    if ctx is not None:
        lines.append(ctx)
    lines.extend(post)
    return lines


def _iter_exceptions(parsed):
    exc = parsed.get("exception")
    if not exc:
        return []
    if isinstance(exc, dict):
        return list(exc.get("values") or [])
    if isinstance(exc, (list, tuple)):
        return list(exc)
    return []


def _frames_for_exception(exc):
    st = exc.get("stacktrace") or {}
    return list(st.get("frames") or [])


def _header_lines(event, exc):
    etype = exc.get("type") or "Exception"
    val = exc.get("value") or ""
    # Two-line title; no platform/event_id/timestamp clutter.
    return [f"# {etype}", val]


def _format_frame_header(frame):
    fn = frame.get("filename") or frame.get("abs_path") or "<unknown>"
    func = frame.get("function") or ""
    lineno = frame.get("lineno")
    in_app = frame.get("in_app") is True
    scope = "in-app" if in_app else "external"

    header = f"### {fn}"
    if lineno is not None:
        header += f":{lineno}"
    if func:
        header += f" in `{func}`"
    header += f" [{scope}]"

    debug_id = frame.get("debug_id")
    if debug_id and not frame.get("mapped"):
        header += f" (no sourcemap for debug_id {debug_id})"
    return [header]


def _format_code_gutter(frame):
    pre, ctx, post = _code_segments(frame)
    if not pre and ctx is None and not post:
        return []

    lineno = frame.get("lineno")
    if lineno is not None:
        start = max(1, int(lineno) - len(pre))
    else:
        start = 1

    lines = list(pre)
    ctx_index = None
    if ctx is not None:
        ctx_index = len(lines)
        lines.append(ctx)
    lines.extend(post)

    last_no = start + len(lines) - 1
    width = max(2, len(str(last_no)))

    out = []
    for i, text in enumerate(lines):
        n = start + i
        if ctx_index is not None and i == ctx_index:
            out.append(f"▶ {str(n).rjust(width)} | {text}")
        else:
            out.append(f"  {str(n).rjust(width)} | {text}")
    return out


def _format_locals(frame):
    vars_ = frame.get("vars") or {}
    if not vars_:
        return []
    lines = ["", "#### Locals", ""]
    for k, v in vars_.items():
        lines.append(f"* `{k}` = `{v}`")
    return lines


def _select_frames(frames, in_app_only):
    if not in_app_only:
        return frames
    filtered = [f for f in frames if f.get("in_app") is True]
    return filtered if filtered else frames


def render_stacktrace_md(event, in_app_only=False, include_locals=True):
    parsed = event.get_parsed_data()
    try:
        apply_sourcemaps(parsed)
    except Exception as e:
        if settings.DEBUG or settings.I_AM_RUNNING == "TEST":
            # when developing/testing, I _do_ want to get notified
            raise

        # sourcemaps are still experimental; we don't want to fail on them, so we just log the error and move on.
        capture_or_log_exception(e, logger)

    excs = _iter_exceptions(parsed)
    if not excs:
        return "_No stacktrace available._"

    stack_of_plates = getattr(event, "platform", None) != "python"
    if stack_of_plates:
        excs = list(reversed(excs))

    lines = []
    for i, exc in enumerate(excs):
        if i > 0:
            lines += ["", "**During handling of the above exception, another exception occurred:**", ""]
        lines += _header_lines(event, exc)

        frames_list = _frames_for_exception(exc) or []
        if stack_of_plates and frames_list:
            frames_list = list(reversed(frames_list))

        frames_list = _select_frames(frames_list, in_app_only)

        for frame in frames_list:
            # spacer above every frame header
            lines.append("")
            lines += _format_frame_header(frame)

            code_listing = _format_code_gutter(frame)
            if code_listing:
                lines += code_listing
            else:
                # brief mention when no source context is available
                lines.append("_no source context available_")

            if include_locals:
                loc_lines = _format_locals(frame)
                if loc_lines:
                    lines += loc_lines

    return "\n".join([s.rstrip() for s in lines]).strip()
