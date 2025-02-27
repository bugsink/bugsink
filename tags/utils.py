from events.ua_stuff import get_contexts_enriched_with_ua
from sentry.utils.safe import get_path


EVENT_DATA_CONVERSION_TABLE = {
    # NOTE that "level" is not included here; Sentry puts this front and center, and although we may give it _some_
    # place in the UI, Bugsink's take is that "level: Error" in an Error Tracker is an open door/waste of space.
    "server_name": "server_name",
    "release": "release",
    "environment": "environment",
    "transaction": "transaction",
}


CONTEXT_CONVERSION_TABLE = {
    "trace": ("trace", "trace_id"),
    "trace.span": ("trace", "span_id"),
    "browser.name": ("browser", "name"),
    "os.name": ("os", "name"),

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
        value = get_path(event_data, lookup_path)
        if value not in [None, ""]:
            tags[tag_key] = value

    # deduce from contexts
    contexts = get_contexts_enriched_with_ua(event_data)

    for tag_key, path in CONTEXT_CONVERSION_TABLE.items():
        value = get_path(contexts, *path)
        if value not in [None, ""]:
            tags[tag_key] = value

    if "trace" in tags and "trace.span" in tags:
        tags["trace.ctx"] = f"{tags['trace']}.{tags['trace.span']}"

    if "browser.name" in tags and (browser_version := tags.get("browser.version")):
        tags["browser"] = f"{tags['browser.name']} {browser_version}"

    if user_tag := deduce_user_tag(contexts):
        tags["user"] = user_tag

    # TODO further tags that are probably useful:
    # url
    # logger
    # mechanism

    return tags
