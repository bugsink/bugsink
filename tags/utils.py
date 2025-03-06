from events.ua_stuff import get_contexts_enriched_with_ua
from sentry.utils.safe import get_path

from issues.utils import get_main_exception


EVENT_DATA_CONVERSION_TABLE = {
    # "level" is not included here; Sentry puts this front and center for the tags; although we give it a non-prominent
    # place in the UI for the event-detail, Bugsink's take is that "level: Error" in an Error Tracker is not useful
    # enough to warrant display-as-tag. Also, for tags you'd generally get 100% identical values for all events in a
    # single issue, so it's not useful for tag-breakdown either. Arguably, for search, a case could be made,
    # _especially_ if you treat Bugsink as a Log Aggregator. However, the (current) position of Bugsink is that we're an
    # Error Tracker first and foremost, and that support for Log messages is only there to not confuse our users (i.e.
    # we should always display the information that we have on hand). But searching for "info-level only" is not a
    # use-case that we're actively supporting.
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

    # TODO maybe useful, but not sure yet; Sentry/GlitchTip give a very prominent place to the "runtime" tag (even an
    # icon in the UI); but it's not clear to me that this is actually useful information. I _know_ that my code is
    # running in language X, right? And I'd generally say "1 project => 1 language" so filtering isn't useful either.
    # Regarding the version, I'd say that's even less useful (famous last words) because how many _bugs_ make it past
    # CI/CD and are still runtime-specific? And even if they are, is it really more likely that you discover that fact
    # by looking at the tag-breakdown of the runtime version than that you'd discover it by drilling down in the
    # stacktrace?
    # runtime
    # runtime.name

    # TODO Device-specific tags are probably useful, because they imply a world where you have your software running on
    # many different devices, and you want to know if a bug is specific to a certain device. But I'd rather get a good
    # use-case for this first (user-supplied).
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

    # TODO url is probably useful, but I imagine that its `mostly_unique` property is not statically known, i.e. some
    # issues may have single url, others may have a few (useful for tag-breakdown) and yet others may have very many
    # (useful for search). We'll tie implementation of this to the implementation of dynamic `is_mostly_unique`
    # determination.
    # url

    # TODO For now this is not supported for the same reason as "level" (see above). But it's probably more useful than
    # level, because it will be more likely be a searchable term that "leads somewhere" (i.e. if you know you have a
    # problem in module X, you can search for it). It's still somewhat annoying to implement (at least if you do the
    # full fallback for all data-layouts) because the API has changed quite a bit recently (see `issues/views.py`)
    # logger

    # Is mechanism useful? For search, probably not (I'm happy to be proven wrong with a specific use-case). For
    # tag-breakdown, even less likely (it would my guess that the values would always be the same for a single issue).
    # mechanism.type

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
