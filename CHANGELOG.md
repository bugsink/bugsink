# Changes

## 1.6.1 (11 June 2025)

Remove hard-coded slack `webhook_url` from the "test this connector" loop.

## 1.6.0 (10 June 2025)

### Slack Alerts

Bugsink 1.6.0 introduces Slack Alerts (through webhooks); see #3.

### Backwards-incompatible changes

* The default number of web processes (gunicorn server workers) in the
  dockerized setup is now equal to `min(cpu_count, 4)`; (it used to be 10).

  set `GUNICORN_CMD_ARGS="--workers=10"` to restore the previous behavior or
  choose a custom number.

### Various Features & Fixes

* Display formatted log message when available (see #111)
* Add 2 env variables to compose-sample.yaml (See #110)
* Add delete functionality for users (See #108)
* Multi-file sourcemaps (See #87)
* Lookup by `debug_id` in dicts: use UUID (See #105)
* Add robots.txt that disallows crawling
* Add HEALTHCHECK command to Dockerfiles (See #98)
* Fingerprint: convert to string before concatenating (See #102)
* Add /health/ready endpoint (See #98)

## 1.5.4 (12 May 2025)

* Add bugsink-util script to allow settings-independent commands to be run
* UX of the `stress_test` command (param cleanup)
* checks on `settings.BASE_URL`
* Show _all_ Request Headers in `CSRF_DEBUG` view (see #100)
* Fix obj not found when visiting project as a non-member superuser

## 1.5.3 (7 May 2025)

* Performance fixes of the issue-list when there are many (millions) of _issues_ (rather than just events) in the
  database; see aad0f624f904 & 0dfd01db9b38.

* Fix: `different_runtime_limit` applying to the wrong DB alias, see 699f6e587d28

* `CREATE_SUPERUSER` shortcut: robust for ':' in password, see 9b0f0e04f4e4

## 1.5.2 (6 May 2025)

Various performance fixes when there are many (millions) of _issues_
(rather than just events) in the database:

* Add index for `Grouping.grouping_key` (and project), see 392f5a30be18, 49e6700d4a81
* Digest: check Grouping.exists only once (save a query)
* Remove `open_issue_count` from homepage; it's too expensive
* Issue Paginator: don't attempt to count the Issues, see 378366105496
* Stress test command: more fat-tailed randomness (d5a449020d03)

Compatibility fix:

* `format_exception` in `capture_or_log_exception`: python 3.9 compatible

## 1.5.1 (24 April 2025)

Various fixes and improvements:

* 2 new tools to get a handle on performance of systems under load:
    * A [snappea-stats] subcommand to gain insight in
    * A page was added at `http://YOURINSTALL/counts/` that shows, for each type of object, the number of objects in the
      DB. (superuser only)

* Fix `different_runtime_limit` race conditions, see 53d4be818334
* `immediate_semaphore`: implement alias "using", see 67f769d3e5be
* `immediate atomic` 'get-write-lock' performance logging: fix it, see f8db5edf82ed

* Various improvements in the yellow warning bar for "backlogged snappea":
    * Better 'yellow bar' for snappea warnings (using Stat info)
    * Oldest task age warning: display as int
    * snappea task warning should itself never slow down the site (max runtime)

* Add some examples to the "conf templates"
    * `EVENT_STORAGES`: add (commented-out) example configuration to `conf_templates`
    * Clarify options for `EMAIL_BACKEND` in the `conf_templates`

* When is the `email_system_warning` shown? change & document
* Snappea foreman: on catastrophic errors, wait for workers, see 9b6fbe523f3c
* Explain tailwind usage during development & vendoring step, see 5c0e45a16db2
* Fix Header/Grouper for Log Messages using deprecated SDKs (See #85)

* `EMAIL_USE_TLS`: false by default (as was documented). See 7c3c19b6c8f2
* `EMAIL_USE_SSL`: `not EMAIL_USE_TLS` by default (avoids crashing on "both
  true" when only `EMAIL_USE_TLS` is explicitly configured

## 1.5.0 (14 April 2025)

Bugsink 1.5.0 introduces preliminary support for sourcemaps.

_preliminary_ because only the following combination (all must apply) of features works:

* Uploading "manually", using `sentry-cli`
* sourcemaps & sources are related using `debug-id`, which must be injected by `sentry-cli`

Tested with the followin `sentry-cli` invocation:

```
uglifyjs captureException.js   -o captureException.min.js   --source-map url=captureException.min.js.map,includeSources
sentry-cli sourcemaps inject captureException.min.js captureException.min.js.map
SENTRY_AUTH_TOKEN=a sentry-cli --url https://YOURBUGSINK/ sourcemaps --org bugsinkhasnoorgs --project=ignoredalso upload .
```

Implemented with 3 endpoints Bugsink-side:

* upload-chunks GET tells the CLI what our capabilities are
* upload-chunks POST allows the CLI to upload the files (the CLI bundles everything first, and adds a manifest)
* assemble-artifact: unpack that thing and put it in the right location.

[This comment contains a longer overview of the current state](https://github.com/bugsink/bugsink/issues/19#issuecomment-2796304379)

### Further Features & Fixes

* Add `EMAIL_USE_SSL` to settings/templates.

* Print full stacktraces when _not_ dogfooding (i.e. when sentry-sdk is not configured).

* Various Dockerfile improvements (See #68 and the top of the Dockerfile for details)

* Allow users to join their own team's projects Fix #56
* Don't crash on non-str tag-values: Fixes #76

* Add `user.id`, `user.username`, `user.email` and `user.ip_address` tags in `deduce_tags`
  allows for direct matching on one of those rather than just "whatever is avaialble"
  (which goes into the not further qualified `user` tag)

## 1.4.2 (1 April 2025)

* `deduce_allowed_hosts`: allow for localhost, see #46
* `retention_max_event_count`: in project settings form
* `issue.stored_event_count`: fix (it was incorrectly calculated). Running the migrations will
    automatically fix the existing values too.
* Fix user tag deduction (user tags were not correctly calculated from the event data)

## 1.4.1 (17 March 2025)

* Bugfixes on the experimental postgres support, see #21, #61
* sqlite: per-query timeout configurable
* Make `EMAIL_TIMEOUT` configurable on Docker, fixes #60

## 1.4.0 (13 March 2025)

### Introducing (Tag-based) Search

Bugsink 1.4.0 [introduces tag-based search](https://www.bugsink.com/blog/introducing-search/).

* Support for searching both **Issues** and individual **Events**.
* Search is built entirely on **tags** (both user-supplied and deduced from event properties).
* **Simple query language**: `key:value` pairs for structured filtering.
* Search is **implemented directly in the database**, ensuring a simple and efficient architecture.

Because tags take such a key role in the implementation of search, the introduction of search is coupled with per-issue
tag overviews, see #36 & #12. i.e. per issue pages show a breakdown-by-tag; and a special page (showing up to 25 values)
for tags is introduced.

NOTE: when upgrading to 1.4.0 tags for already-seen events are not automatically calculated (for large databases, this
could make migrating very annoying). You can either wait a while (the tags for as of yet unseen events will be added)
or run the `init_tags` command to determine the tags for the already-existing issues and events.

### Further Features & Fixes

* Postgres: experimental support: our testsuite now runs against postgres, and configuring the Docker image to run with
  a postgres backend is possible. No further testing has been done, but this at least makes such experiments possible.
  See #21

* Createsuperuser pre-start: don't do that when _any_ users exist in the DB (Fixes #54)

* Show remaining (in db, AKA 'available') number of events in the issue-list (when some events have been evicted from
  the DB, the issue list shows the _actually availale_ number of events in a smaller font next to the total seen number.

* Details page: be robust for top-level message-as-string (Fixes #55)

* Add 'level' to logentry event details

* Issue.calculated_* fields: fix lengths (fixes an issue on MySQL)

## 1.3.0 (20 February 2025)

### Introduce FileEventStorage

An (optional) way to store the `event_data` (full event as JSON)
outside the DB. This is expected to be useful for larger setups,
because it gives you:

* A more portable database (e.g. backups); (depeding on event size
  the impact on your DB is ~50x.
* Less worries about hitting "physical" limits (e.g. disk size, max
  file size) for your DB.

Presumably (more testing will happen going forwards) it will:

* Speed up migrations (especially on sqlite, which does full table copies)

However: Ingestion speed does not seem to notacibly changed (either
way) with this change.

Related utilities:

* `migrate_to_current_eventstorage` command: a command to move data over.
* `cleanup_eventstorage` command: a "vacuum" of sorts.

### Further Features

* Pagination on the Issues list
* Event-detail UI for Logentries: show `logentry.message` and `logentry.params`
* UI: thousand-separators for counts
* Support for top-level `message` in events (See #43)
* `nuke_events` command improvements: more consistent behavior, better confirmation.
* `make_consistent` command improvements: more affected cases, run in transaction
* `migrate` command: always shows timings
* `showstat` command: `digestion_speed`
* Send welcome email: as a command
* Support for CORS

### Fixes

* transaction semaphore: ensure release for exceptions while _entering_ the transaction

### Cleanup / refactoring

* Move MoreLoudlyFailingTransport out of the default 'eat_your_own_dogfood' conf
* allow long-running queries on long-running commands (`nuke_events`, `make_consistent`)
* DB indexes for the issue-lists (including filters)
* Don't 'eat your own dogfood' (send errors to backend) while running tests
* `delete_with_limit` was removed; this removes one tie-in to MySQL/Sqlite (See #21)
* Print task's name in Snappea log when "Done"

## 1.2.0 (11 February 2025)

### Features

* Docker: The SQLite database now defaults to being stored in `/data/`, with a warning if the directory needs to be created.
* Show 'event grouping', 'handled' and 'mechanism' in the event details
* Ingestion performance fixes (most notable when >1M events are stored). See 615d2da4c8b5
* UI performance fixes (most notable in the UI, when >1M events are stored). See 86e8c4318bc2

### Bug Fixes

* Transaction semaphore fixes prevent deadlocks
* Various fields are cut off at max length to avoid (1406, "Data too long for column ...")` errors in MySQL.
* Ensured `digested_at` time is set correctly.
* Added indexes on fields used for ordering
* UI: 'This might mean' refers to 'No open issues'; make this show in the interface

### Cleanup / refactoring

* Remove 2 fields that were "temporary [..] to get a sense of the shape of the data
* Set up dependabot
* Update dependencies (as per dependabot)
* Datamodel: `Event.grouping`, which ensures every event has a consistent Grouping associated with it.
* Move 'DESIGN*' docs out of repo
* Mention Security Policiy in CONTRIBUTING.md
* squashmigrations (faster startup for fresh installations)
