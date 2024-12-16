## Findings about event.schema.json

There are 2 locations where this file can be sourced (a good and a bad one):
The 2 locations have diverged (of course!)

### sentry-data-schemas

In the sentry-data-schemas repo:

* https://raw.githubusercontent.com/getsentry/sentry-data-schemas/main/relay/event.schema.json

This is MIT-licenced.

The repo contains a setup.py, but:

* the result of that didn't make it to pypi
* the result of that is Python files (mypy) and does not contain the json file.

### Sentry (the main repo)

In the sentry repo:

* https://github.com/getsentry/sentry/blob/master/src/sentry/issues/event.schema.json
* https://github.com/getsentry/sentry/blob/6b96e8f0c484/src/sentry/issues/event.schema.json

This is not 'real' Open Source.

### Notes on divergence:

The main point of divergence (other than just the fact that the laws of nature force code to drift apart) is that
the sentry's codebase has, as per the commmit that adds it:

> added `"project_id"` field (in the API this would have been added from the URL path)

See also the "caveats" section here:

https://github.com/getsentry/sentry-data-schemas?tab=readme-ov-file#relayeventschemajson

In short, the more reasons to just use the "upstream" API.

Said in another way: we act more as the "relay" than as "getsentry/sentry", because we do ingest straight in the main
process. So we should adhere to the relay's spec.
