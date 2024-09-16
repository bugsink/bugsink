from user_agents import parse as ua_parse


def enrich_contexts_with_ua(parsed_data):
    # GlitchTip has some mechanism to get "synthetic" (i.e. not present in the original, UA-header derived) info into
    # first the contexts, which is then propagated (with a whole bunch of other info from contexts) to the tags. Both
    # these steps happen on-digest.
    #
    # I'm not sure what I want myself... on the one hand I'm not a fan of this kind of magic. On the other: if the data
    # usually lives in the "context" (e.g. in the JS world), you might as well synthesize it into that location when iit
    # is not in that location in the data (but is available through other means).
    #
    # my set of samples has very little data for contexts, so it's hard to get a feel for it. I imagine that having this
    # info available in tags can be useful for searching, or for getting a quick feel of the data (tags show up in the
    # RHS of various screens). But again: too little data to tell yet. Add to that that I'm much less inclined than my
    # competitors to give OS/browser info the main stage (icons? yuck!). So we'll just parse it, put it "somewhere", and
    # look at it again "later".
    contexts = parsed_data.get("contexts", {})

    ua_string = (parsed_data.get("request", {}).get("headers", {})).get("User-Agent")
    if ua_string is None:
        return contexts

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

    return contexts
