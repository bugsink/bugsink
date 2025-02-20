# Changes

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

* `migrate_to_current_eventstore` command: a command to move data over.
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
