from events.ua_stuff import get_contexts_enriched_with_ua
from sentry.utils.safe import get_path

from issues.utils import get_main_exception


EVENT_DATA_CONVERSION_TABLE = {
    # "level" is not included here; Sentry puts this front and center for the tags; although we give it a non-prominent
    # place in the UI for the event-detail, Bugsink's take is that "level: Error" in an Error Tracker is not useful
    # enough to warrant display-as-tag, nor even is it a searchable term.
    # "level": ("level",),

    "server_name": ("server_name",),
    "release": ("release",),
    "environment": ("environment",),
    "transaction": ("transaction",),
}


MAIN_EXCEPTION_CONVERSION_TABLE = {
    "handled": ("mechanism", "handled"),
}


CONTEXT_CONVERSION_TABLE = {
    "trace": ("trace", "trace_id"),
    "trace.span": ("trace", "span_id"),
    "browser.name": ("browser", "name"),
    "browser.version": ("browser", "version"),
    "os.name": ("os", "name"),
    "os.version": ("os", "version"),

    # TODO probably useful, simply not done yet:
    # runtime
    # runtime.name
    # device.something
}


def deduce_user_tag(contexts):
    # quick & dirty / barebones implementation; we don't try to mimick Sentry's full behavior, instead just pick the
    # most relevant piece of the user context that we can find. For reference, Sentry has the concept of an "EventUser"
    # (`src/sentry/models/eventuser.py`)

    if "user" not in contexts:
        return None

    for key in ["id", "username", "email", "ip_address"]:
        if contexts["user"].get(key):
            return contexts["user"][key]

    return None


def _convert_non_strings(value):
    if isinstance(value, bool):
        return str(value).lower()
    return value


def deduce_tags(event_data):
    """
    Deduce tags for `event_data`. Used as an "opportunistic" (generic) way to implement counting and searching. Although
    Sentry does something similar, we're not striving to replicate Sentry's behavior (tag names etc). In particular, we
    feel that Sentry's choices are poorly documented, the separation of concerns between events/contexts/tags is
    unclear, and some choices are straight up not so great. We'd rather think about what information matters ourselves.
    """

    # we start with the explicitly provided tags
    tags = event_data.get('tags', {})

    for tag_key, lookup_path in EVENT_DATA_CONVERSION_TABLE.items():
        value = get_path(event_data, *lookup_path)

        # NOTE: we don't have some kind of "defaulting" mechanism here; if the value is None / non-existent, we simply
        # don't add the tag.
        if value not in [None, ""]:
            tags[tag_key] = _convert_non_strings(value)

    # deduce from main exception
    main_exception = get_main_exception(event_data)
    for tag_key, lookup_path in MAIN_EXCEPTION_CONVERSION_TABLE.items():
        value = get_path(main_exception, *lookup_path)

        if value not in [None, ""]:
            tags[tag_key] = _convert_non_strings(value)

    # deduce from contexts
    contexts = get_contexts_enriched_with_ua(event_data)

    for tag_key, path in CONTEXT_CONVERSION_TABLE.items():
        value = get_path(contexts, *path)
        if value not in [None, ""]:
            tags[tag_key] = _convert_non_strings(value)

    if "trace" in tags and "trace.span" in tags:
        tags["trace.ctx"] = f"{tags['trace']}.{tags['trace.span']}"

    if "browser.name" in tags and "browser.version" in tags:
        tags["browser"] = f"{tags['browser.name']} {tags['browser.version']}"

    if "os.name" in tags and "os.version" in tags:
        tags["os"] = f"{tags['os.name']} {tags['os.version']}"

    if user_tag := deduce_user_tag(contexts):
        tags["user"] = user_tag

    # TODO further tags that are probably useful:
    # url
    # logger
    # mechanism

    return tags


def is_mostly_unique(key):
    if key.startswith("user"):
        return True

    if key.startswith("trace"):
        return True

    if key in ["browser.version", "browser"]:
        return True

    if key in ["os.version", "os"]:
        return True

    return False
