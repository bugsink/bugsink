Some results of a small stress test (event-size: 50KiB) d.d. 27 Jun 2024

15 projects with `10_000` events maximum each.

Most interesting pictures: `df` and `snappea_queue_size`

What we can see: there is a backlog this time.

C.  8:00 UTC: Start of stress test
C.  9:00 UTC: Per project max event is being hit; disk usage increase slows down.
C. 15:00 UTC: I turned off the stress test; from that point the backlog (and hence the disk usage of undigested events) was reduced.
C. 16:00 UTC: Backlog reduced to 0

Post-test (next day) db size is 5518716928 (5.2GiB)

Open question: what is causing the increase of disk usage between 9:00 and 16:00 (i.e. between max-hit and test-done). Some options:

* Logs
* DB inefficiencies (no vacuum yet)
* Issues / other items in the DB.
    Issues seems unlikely TBH: there is some increase in the number of issues (we have random event types, with a long-tail distribution, so new issues may always arise, but after the test there are only 6611 total issues)
