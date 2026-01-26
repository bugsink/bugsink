# Changes

## 2.0.12 (26 January 2026)

### Fixes:

* Quota checks: don't get confused (so much) by eviction, see c157827a3050
* `cleanup_eventstorage` command: don't fail when no storage initialized, see 45dc85a38288
* `EventStorage.list` must return UUIDs for usage in .delete, see c8457ed9bd45
* Don't rely on SDK-provided `event_id` for ingest-digest handover, see 6ab3fa56200e, and 9e8f59ebc1b1
* `cleanup_events` (after delete): push out of transaction, see 4130cd240205 and 7f726cad8fc9
* Add simple command to delete the oldest events until under retention max, see 941490605355
* `FileEventStorage` config forward-compatible, see 5099d697493f
* `migrate_to_current_eventstorage` command: don't crash when there are 'very many' events, see 34cf7dc868f5

### Upgrading

The optional management command `fix_project_digest_order` can be run in
addition to migrations; this will make rate-limiting quota work more
correctly immediately.

(if you don't care, this will become eventually correct as the old data
fades away).

## 2.0.11 (20 January 2026)

* Add brotli and gzip filestorages, see 5b345e0535c9
* Apply max retention from settings even if stored project value is higher, see 1f1b06b74dd0
* Max retention event count: guard the API, see d3beed517217
* Max event retention: don't mention a negative budget, see 0a39ce16f487
* New project: suggest no more than the legal retention, see 0cdb6c0afdab

## 2.0.10 (14 January 2026)

* FileStorage: basepath configurable using `get_basepath` (callable), 2561f5602a7b

## 2.0.9 (13 January 2026)

* Add event URL for the "external" (SDK-provided) ID, see #291
* Add OpenAPI link to navigation bar, see #302 / #301
* Adding info to contributing guidelines, see #303

## 2.0.8 (10 January 2026)

* Improve default Sentry SDK settings for Python, Fix #298
* Fix background of event search inputs in dark mode, see #300
* Add missing tailwindcss dependencies (for development)
* `MAX_RETENTION[_PER_PROJECT]` as a setting
* More fully disable the admin when `USE_ADMIN=False`, See #131
* quota exceeded: show a message
* Project quota: pick up on settings-changes
* Setting & check for site-wide per-month event ingestion maximum
* Add modelcounts command; useful in the context of housekeeping when servers are down
* Fix exception for unsupported envelope items / when minidump feature is off. See #293

## 2.0.7 (6 January 2026)

### New & Improved Alert backends

* Adds the Mattermost Alert Backend, see #278, #253, #277
* Adds the Discord Alert Backend, see #279, #121

### Minidump API Endpoint: _Experimental_

This release contains _code_ that supports Minidumps, and which can be turned on with the
feature-flag (setting) `FEATURE_MINIDUMPS`.

However, as it stands, this code should be seen as development-only: it has not
passed security-review yet, which means it opens your Bugsink-installation to DOS-like
attacks.

See #270, #82.

### Other changes

* Fix `never_evict` for the "conditional ummute" case, see #292
* ingest ParseError: don't raise a 500; make this the SDK's problem (400), see 4fe8bd3fad44
* Upgrade Verbose CSRF Middleware to match Django 5.2, see e3f1c92fd17f
* Fix for pygements mishandling a weird case w/ ruby, see 4564131ff532
* Raise 413 for the 'content too large' case
* Slack alerts: issue title in message title, fix #283
* Channel support for Mattermost message backend, see #281
* Discord alert backend: send 'valid' URLs only, fix #280
* yesno filter: just don't return None ever, see 9b2acddf206b
* tailwind update, see bddc2e8f640e
* Link to 'all tags' in the 'tags' RHS box, see eeac2e750c05
* 'files' is a bugsink module too; reflect in `eat_your_own_dogfood`, see 74a04f6ea1dc
* Don't log emails to 0 recepients, see #86
* Fix member counts on project/team list, they were at most 1, see a93f369ad749
* Support request.body when doing Chuncked Transfer Encoding, see #9
* Fix inefficient bytes concatenation when `KEEP_ENVELOPES` != 0, see 0432451e8e8b
* Compression decoding errors: return 400 rather than 500, see 53bea102d911
* Support Python 3.14, see #267

## 2.0.6 (8 November 2025)

### Security

Add a mitigation for another DOS attack using adverserial brotli payloads.
Similar to, but distinct from, the fix in 2.0.5.

## 2.0.5 (8 November 2025)

### Security

Add a mitigation for certain DOS attacks using adverserial brotli payloads, see #266

### Backwards incompatible changes

Fail to start when using non-sqlite for snappea, See #252

Since this was always recommended against, and probably broken anyway, this is not
expected to be backwards incompatible _in practice_, but it is at least in prinicple.


### Other changes

* Markdown stacktrace: render with all frames, See 9cb89ecf46a7
* Add database vendor, version and machine arch to phonehome message, see d8fef759cabc
* Fix redirect on single-click actions when hosting at subdomain, Fix #250
* 'poor mans's DB lock: lock the right DB; See e55c0eb417e2, and #252 for context
* Add more warnings about using non-sqlite for snappea in the conf templates, See #252
* `parse_timestamp`: _actually_ parse as UTC when timezone not provided, see 8ad7f9738085
* Add debug setting for email-sending, Fix #86
* docker-compose-sample.yaml: more clearly email:password, See #261
* create snappea database on Docker start rather than image build, See #244

## 2.0.4 (9 October 2025)

* `convert_mariadb_uuids` command to fix UUID column problems on MariaDB

If you upgrade (or have upgraded) from Bugsink < 2.0 to any 2.0.x version you
need to run this command (and you need 2.0.4 to be able to run it).

See #226

## 2.0.3 (5 October 2025)

* Simplify login template (f8be55da89dd)
* Better hints for malformed Token headers (d0e7b75dbba1)
* API: datetime objects always in UTC (afd31d226352)
* API: remove `is_deleted` as a field (0ca3e33e1f81)
* Fix null constraint failure when `remote_addr` is `None` and user is '{{auto}}' (See #229)

## 2.0.2 (22 September 2025)

* Fix broken checkbox in issue list (See #225)

## 2.0.1 (16 September 2025)

2 docker-related fixes (e346f8d5c22a and aa799e9c940f)

## 2.0.0 (16 September 2025)

### Backwards incompatible changes

* Python 3.9 is no longer supported

[Unless you're running Debian Bullseye this will not affect you](12af5302efdd).

The minimum supported version for the database backends has been raised to:

* SQLite ≥ 3.31.0
* MySQL ≥ 8.0.11
* PostgreSQL ≥ 14
* MariaDB ≥ 10.5

[Overview of typical versions in various
OSes](https://github.com/bugsink/bugsink/pull/89#issuecomment-3253843464)

#### Non-root Docker

The provided Docker container no longer runs the Bugsink process as the root
user. This improves security (defense in depth), but may require changes to
your setup (i.e. volume permissions).

Setups that mount the `/data` dir as a volume must ensure that the directory is
owned by UID 14237 (the user the process runs as inside the container).
[Further migration
instructions](https://github.com/bugsink/bugsink/issues/176#issuecomment-3139184180)

If you have not mounted any volumes, you will not be visibly affected by this change.

#### Hardening of Temporary-Directory

Bugsink now requires ownership of the `INGEST_STORE_BASE_DIR` directory to avoid
certain classes of local privilege escalation attacks. (see #174)

If you manually configured this directory to be something that the process
running Bugsink _cannot_ own (e.g. to `/tmp/` without a further subdir), you
must change it to something it can own (e.g. the default of `/tmp/bugsink/ingestion`)

The Docker image is not affected by this (manual configuration wasn't possible to
begin with).

### Various Improvements & Fixes

* When selecting text in the stacktrace frameHeader, don't toggle the frame (d62d016be3aa)
* i18n support and Chinese translation (See #192, #161)
* minor changes to `send_json` util (f0d3667121ab, c38ca8c58a4c)
* Docker: bugsink-show-version on-start (42ba5a71facc)
* Implement `vacuum_ingest_dir` management command (See #163)
* add dark-mode default for border color (833776c646f5)
* API: first version (see #211, #146)
* docker compose sample: use alpine postgres (#208)
* docker compose sample: fix major version (#207)
* Improve Slack alerts to work with Mattermost (#203)
* Fix #97: implement /api/0/ endpoint
* Move conf utils to separate module
* transaction: use connection.vendor instead of settings.DATABASES engine check (see #117)
* support hosting at subpath (#201, #93)

### Dependency updates

* Replace `python-sourcemap` with `ecma426` (see 0764024389fc)
* django 4.2 => django 5.2
* Tailwind 3 => Tailwind 4
* django-tailwind 3.6 => 4.2
* `inotify_simple` => 2.0

## 1.7.6 (1 August 2025)

* envelope-headers `sent_at` check should allow 00+00 (See #179)
* evenlope-header validation failure should not lead to envelope-rejection (See #179)

## 1.7.5 (31 July 2025)

### General Improvements

* Add failure visibility for alert backends (See #169)
* Add per-month quota for email-sending (Fix #34)
* Store `remote_addr` on the event (Fix #165)
* Use `remote_addr` for `'{{auto}}'` `ip_addr` tags (See #165)
* `PID_FILE` check: make optional (See #99)
* `PID_FILE` check: don't use in docker/systemd (Fix #99)
* Breadcrumb timestamps: display harmonized w/ rest of application (ceca12940bd5)

### Sourcemaps: better debugging

* sourcemaps: Uploaded, but ignored, files: warn (See #158)
* Sourcemaps: Warn (in the logs) on multiple-debug-ids source uploads (See #157, #158)
* Debug IDs for missing sourcemaps: show them right in the stacktrace (See #158)
* Sourcemap Images IDs: show those in event details (See #158)

### Configuration / Settings

* `SINGLE_USER` implies `SINGLE_TEAM` and more (Fix #162)
* Docker config: `BEHIND_PLAIN_HTTP_PROXY` (Fix #164)
* Development setting: keep artifact bundles (1aef4a45c2dc)

### Security Hardening

* CI pipeline security checks with Bandit (See #175)
* Envelope parsing validates headers strictly (See #173)
* Use `django.utils._os.safe_join` to construct paths (see #173)

### Internal Tooling

* Remove the Django Debug Toolbar entirely (Fix #168)
* semaphore-for-db-write-lock: sqlite only (See #117)
* `send_json` utility: make envelope API the default (13226603ec7a)

## 1.7.4, 1.6.4, 1.5.5, 1.4.3 (29 July 2025)

Security release. Upgrading is highly recommended. See [this
notice](https://github.com/bugsink/bugsink/security/advisories/GHSA-q78p-g86f-jg6q)

## 1.7.3 (17 July 2025)

Migration fix: delete TurningPoints w/ project=None (Fix #155)

## 1.7.2 (17 July 2025)

Various fixes:

* Dark mode: use monokai style from pygments (Fix #152)
* add `vacuum_files` command (Fix #129)
* Artifact Bundle upload: clean up after extract (See #129)
* Add API catch-all endpoint for logging (Fix #153)
* File-upload: chunk-size of 2MiB (Fix #147)
* Sourcemaps upload: max file size 2GiB (See #147)
* Auto-clean binlogs on docker compose (sample) for mysql (See #149)
* Remove platform 'choices' from Event.model (See 403e28adb410)
* Better `ALLOWED_HOSTS` misconfig error-message (Fix #148)
* As per the "little red box on" #120
* Fix wasted space at certain width in stacktrace UI (See #120)
* Fixed command's 'running in background' output (See 770ccb16225e)
* Project-edit: redirect to list on-save (See 2b46bfe9a114)
* `cleanup_eventstorage` command: be more clear when no `event_storage` is actually configured (See b2769d7202b6)
* Don't crash on illegal values for platform (See #143, #145)
* Support 'crystal' platform (Fix #145)
* Support 'powershell' platform (Fix #143)

## 1.7.1 (10 July 2025)

Fix: user-related forms broken by unclosed link

## 1.7.0 (9 July 2025)

Bugsink 1.7.0 introduces Dark Mode (See #40, #125)

### Housekeeping

A number of options to clean up unwanted or unneeded data have been added:

* Project Deletion (See #50, #137)
* Issue Deletion (See #50)
* Vacuum Tags command (See #135)
* `vacuum_eventless_issuetags` command (see #134, #142)

How these commands/tools relate to each other and may be used is [documented on
the website](https://www.bugsink.com/docs/housekeeping/)

### Various small fixes

* Skip `ALLOWED_HOSTS` validation for /health/ endpoints (see #140)
* `get_system_warnings` as a callable (see c2bc2e417475)
* `store_tags`: support 'very many' (~500) tags (see d62e53fdf8e7)
* Snappea: refuse to start in `TASK_ALWAYS_EAGER` mode (see aa255978b776)
* Sentry-SDK requirement, unpin minor version (see a91fdcd65673)

## 1.6.3 (27 June 2025)

* fix `make_consistent` on mysql (Fix #132)
* Tags in `event_data` can be lists; deal with that (Fix #130)

## 1.6.2 (19 June 2025)

* Too many quotes in local-vars display (Fix #119)

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
