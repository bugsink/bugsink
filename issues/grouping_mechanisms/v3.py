from django.utils.encoding import force_str

from sentry.at_597d25951d00.grouping.strategies.message import normalize_message_for_grouping
from sentry.at_906235e0aa31.grouping.component import GroupingComponent

from .building_blocks.v1 import get_main_exception, get_title_for_exception_type_and_value, get_values


# Bugsink-side adaptor: Sentry's GroupingComponent is vendored, but the event traversal and frame rules here are ours.
NON_APP_PATH_RULES = (
    ("**/site-packages/**", "/site-packages/"),
    ("**/dist-packages/**", "/dist-packages/"),
    ("**/node_modules/**", "/node_modules/"),
    ("**/vendor/**", "/vendor/"),
)
NON_APP_MODULE_PREFIXES = (
    "django.",
    "java.",
    "javax.",
    "jdk.",
    "org.springframework.",
    "org.apache.",
    "io.sentry.",
)


def default_issue_grouper(data, calculated_type, calculated_value):
    return get_grouping_candidates(data, calculated_type, calculated_value)[0]["key"]


def get_grouping_candidates(data, calculated_type, calculated_value):
    frames = _get_stacktrace_frames(data)
    if not frames:
        return [_message_candidate(calculated_type, calculated_value)]

    system_component = _exception_component("system", frames, calculated_type, calculated_value)
    app_component = _exception_component("app", frames, calculated_type, calculated_value)

    candidates = []
    if app_component.contributes:
        candidates.append(_candidate("app", app_component))

    candidates.append(_candidate("system", system_component))
    return candidates


def _message_candidate(calculated_type, calculated_value):
    normalized_value = normalize_message_for_grouping(force_str(calculated_value))
    title = get_title_for_exception_type_and_value(calculated_type, normalized_value)
    component = GroupingComponent(
        id="message",
        values=[
            GroupingComponent(id="type", values=[force_str(calculated_type)]),
            GroupingComponent(id="value", values=[normalized_value]),
        ],
    )
    return {
        "name": "message",
        "key": title,
        "component": component.as_dict(),
    }


def _candidate(name, component):
    return {
        "name": name,
        "key": component.get_hash(),
        "component": component.as_dict(),
    }


def _exception_component(variant, frames, calculated_type, calculated_value):
    stacktrace_component = _stacktrace_component(variant, frames)
    value_component = GroupingComponent(id="value", values=[force_str(calculated_value)] if calculated_value else [])
    if stacktrace_component.contributes and value_component.contributes:
        value_component.update(contributes=False, hint="ignored because stacktrace takes precedence")

    return GroupingComponent(
        id=variant,
        values=[
            GroupingComponent(
                id="exception",
                values=[
                    GroupingComponent(id="type", values=[force_str(calculated_type)] if calculated_type else []),
                    value_component,
                    stacktrace_component,
                ],
            )
        ],
    )


def _stacktrace_component(variant, frames):
    frame_components = []
    for frame in frames:
        frame_component = _frame_component(frame)
        in_app, hint = _frame_appness(frame)

        if variant == "app":
            frame_component.update(hint=hint)
            if not in_app:
                frame_component.update(contributes=False)

        frame_components.append(frame_component)

    hint = None
    if variant == "app" and not any(frame_component.contributes for frame_component in frame_components):
        hint = "ignored because stacktrace contains no in-app frame"

    return GroupingComponent(id="stacktrace", values=frame_components, hint=hint)


def _frame_component(frame):
    values = []
    module = force_str(frame.get("module") or "")
    filename = force_str(frame.get("filename") or frame.get("abs_path") or "")
    function = force_str(frame.get("function") or "")
    context_line = force_str(frame.get("context_line") or "")

    if module:
        values.append(GroupingComponent(id="module", values=[module]))
        if filename:
            values.append(GroupingComponent(
                id="filename",
                values=[filename],
                contributes=False,
                hint="ignored because module takes precedence",
            ))
    elif filename:
        values.append(GroupingComponent(id="filename", values=[filename]))

    if function:
        values.append(GroupingComponent(id="function", values=[function]))

    if context_line:
        values.append(GroupingComponent(
            id="context_line",
            values=[context_line],
            contributes=False,
            hint="not used by Bugsink v3",
        ))

    if not values:
        return GroupingComponent(id="frame", contributes=False, hint="frame has no grouping data")

    return GroupingComponent(id="frame", values=values)


def _frame_appness(frame):
    if frame.get("in_app") is not None:
        if frame.get("in_app"):
            return True, "marked in-app by the client"
        return False, "marked out of app by the client"

    path = force_str(frame.get("filename") or frame.get("abs_path") or "").replace("\\", "/")
    for rule, needle in NON_APP_PATH_RULES:
        if needle in path:
            return False, f"marked out of app by built-in stacktrace rule (path:{rule} -> -app)"

    module = force_str(frame.get("module") or "")
    for prefix in NON_APP_MODULE_PREFIXES:
        if module == prefix[:-1] or module.startswith(prefix):
            return False, f"marked out of app by built-in stacktrace rule (module:{prefix}* -> -app)"

    return True, "marked in-app by Bugsink default"


def _get_stacktrace_frames(data):
    exception = get_main_exception(data)
    if exception is not None:
        frames = _frames_from_stacktrace(exception.get("stacktrace"))
        if frames:
            return frames

    frames = _frames_from_stacktrace(data.get("stacktrace"))
    if frames:
        return frames

    threads = get_values(data.get("threads"))
    if not threads:
        return []

    for thread in reversed(threads):
        frames = _frames_from_stacktrace(thread.get("stacktrace"))
        if frames and (thread.get("crashed") or thread.get("current")):
            return frames

    for thread in reversed(threads):
        frames = _frames_from_stacktrace(thread.get("stacktrace"))
        if frames:
            return frames

    return []


def _frames_from_stacktrace(stacktrace):
    if not stacktrace:
        return []

    frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else stacktrace
    if not frames:
        return []

    return [frame for frame in frames if frame]
