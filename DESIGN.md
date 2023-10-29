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


CLI-first

proxying should be a primitive
    i.e. local client should be similar to servers.
    (passing events is natural)


built from understood/known performance characteristics 


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



Event-based from the ground up.
    because "duh"... this is a textbook event system
    because stability: easier to reason about costs this way.
    because easier to get performant: do your calculations incrementally (e.g. quota usage becomes a +=1 operation)



TECHNICAL CHOICES:

mysql v.s. postgres (v.s. sqlite): make an _informed_ decision



NEXT UP

Start building
    motto: off the shelve and boring components, but with an architecture which takes replacability in mind

    ingesting  first
        as a simple Django app which dumps everything into a textfield (this is TSTTCPW)

        this also allows for 

    dogfooding becomes possible: 
        turn on sentry-SDK and send issues your own way.

    a bunch of example events are availabe in e.g. GlitchTip.

install both GlitchTip and Sentry locally.
    optie 1: met de aangeraden docker-compose
    optie 2: the "developer" view (misschien beter als je pdb wilt kunnen doen??)


NEXT READING SESSION: last OS version of sentry itself.

