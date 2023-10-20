## Goals

* Simplicity
* Stability: easy to deploy; deploy once, and then forget it.

Not "feature rich"

Get *notified* about *programming errors* (not: connection errors) as they occur.
Enough *context* to solve these errors. 

On-prem running is the expected default.

They sent a monolith to catch a monolith.

Flowing from desire for "stability":

* quota-from-the-ground-up (because otherwise: accidental DDOS)
* thinking about resource-usage from-the-ground-up.


Solve as much client-side as possible.

What you care about: "issues", not "events"
    * issue-grouping
    * We don't make money per-issue, we don't want to know about re-occurrences (or we want to know only a little about them)


How valuable is the data? do we care about throwing out info?
    "not as valuable as a running system"
    errors that you care about will likely re-occur.
    still: it's nice to not lose information.


Splitting the issue-database from the organizational database?
    "maybe"
        con: extra complexity
        pro: these things have different backup/reproduction regimes
            the issues (other than "resolution") can be reconstructed from  



