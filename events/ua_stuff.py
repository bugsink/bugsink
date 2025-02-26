import logging

logger = logging.getLogger("bugsink.events.ua_stuff")


def get_contexts_enriched_with_ua(parsed_data):
    # GlitchTip has some mechanism to get "synthetic" (i.e. not present in the original, UA-header derived) info into
    # first the contexts, which is then propagated (with a whole bunch of other info from contexts) to the tags. Both
    # these steps happen on-digest.
    #
    # I'm not sure what I want myself... on the one hand I'm not a fan of this kind of magic. On the other: if the data
    # usually lives in the "context" (e.g. in the JS world), you might as well synthesize it into that location when it
    # is not in that location in the data (but is available through other means).
    #
    # My set of samples has very little data for contexts, so it's hard to get a feel for it. I imagine that having this
    # info available in tags can be useful for searching, or for getting a quick feel of the data (tags show up in the
    # RHS of various screens). But again: too little data to tell yet. Add to that that I'm much less inclined than my
    # competitors to give OS/browser info the main stage (icons? yuck!). So we'll just parse it, put it "somewhere", and
    # look at it again "later".

    # lazy import for performance, because of the many compiled regexes in the user_agents module this takes .2s (local
    # laptop as well as on random GCP server). When this is a top-level import, this cost is incurred on the first
    # request (via urls.py), which is a problem when many first requests happen simultaneously (typically: through
    # the ingestion API) and these contend for CPU to do this import. ("cold start in a hot env"). Making this import
    # lazy avoids the problem, because only the first UI request (typically less hot and more spaced out) will do the
    # import.
    from user_agents import parse as ua_parse

    try:
        contexts = parsed_data.get("contexts", {})

        ua_string = (parsed_data.get("request", {}).get("headers", {})).get("User-Agent")
        if ua_string is None:
            return contexts

        if isinstance(ua_string, list):
            if len(ua_string) == 0:
                return contexts
            ua_string = ua_string[0]  # assuming: it's always just one, and if it's not we just pick that anyway

        user_agent = ua_parse(ua_string)

        if "browser" not in contexts:
            contexts["browser"] = {
                "name": user_agent.browser.family,
                "version": user_agent.browser.version_string,
            }

        if "os" not in contexts:
            contexts["os"] = {
                "name": user_agent.os.family,
                "version": user_agent.os.version_string,
            }

        if "device" not in contexts:
            contexts["device"] = {
                "family": user_agent.device.family,
                "model": user_agent.device.model,
                "brand": user_agent.device.brand,
            }
    except Exception as e:
        # We take the approach of "do not fail to display the event" here. If we can't enrich the contexts with UA info,
        # we'll just log it and move on.

        logger.warning(
            "Failed to enrich contexts with User-Agent info for %s (%s)",
            ua_string, type(ua_string).__name__, exc_info=e)

    return contexts
