# Changes

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
* Datamodel: `Event.grouping`, which ensures every event has a consistent **Grouping** associated with it.
* Move 'DESIGN*' docs out of repo
* Mention Security Policiy in CONTRIBUTING.md
* squashmigrations (faster startup for fresh installations)
