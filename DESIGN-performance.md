## Some thoughts on performance

### 18 July surprise

In the last few days I've been observing 85/s requests ingestion. What has changed? No idea...

### Thoughts after -wal cleanup (better connection closing)

There seems to be a small drop in ingestion performance, to approx. 30/s events. Given that this was (in "Original
thoughts") the max, this is fine (for the increased (presumed) stability). (Pre-wal-cleanup this was approx 40/s)

If this becomes a problem, the thing to consider is "keeping threads, and associated connections, open in the foreman".

### Thoughts after implementing eviction

(See also contents of ./performance/stress-with-eviction/)

* Surprise 1: 50 events/s (60% more than what I found below)
* Surprise 2: in this config, I _am_ getting snappea backlog.

### Original thoughts

Now that we have playground.bugsink.com, I could get some real data on that system too.

I suppose the most "interesting" finding is that the ~30/s events I can handle seem to be entirely limited by the
(https?) nginx stack.

This also means that, in this setup, snappea is able to deal with "postponed" work basically as fast as the frontend can
deliver it, i.e. there is no actual backlog. Which raises some serious(?) questions about snappea in this setup.

Some things I played with (more or less in order I did them):

* try to remove the (physical) network from the equation by doing local-loopback
* use compression (brotli) to avoid network overhead
* compare with my local laptop
* drop actual handling of the request, i.e. just do a `request.read(); return HttpResponse()`
* remove nginx from the equation and just connect on `:8000`

Some numbers:

All measurements are with a 50k event. (NOTE: after removal of whitespace this is actually a 40k event)

* Starting point is ~30/s. local to playground; actual (non-immediate) handling of events. varying number of gunicorn
  and snappea workers doesn't seem to do much.

* local loopback on playground.bugsink.com: ~21/s. i.e. it's slower. Presumably: the cost of running the stress test.

* local loopback on playground.bugsink.com, but dropping the request on the floor: ~25/s.

* compressing as brotli and doing local -> playgrond: ~18/s. Surprisingly the cost of unpacking is larger than the
  advantage of having to deal with less data.

* locally (laptop), I got to ~280/s with actual handling turned on. This is where I (slightly) outrun snappea.

* locally with drop-to-floor I got to ~455/s. Noteworthy: this is not even twice as fast as the "real" (postponed)
  handling. i.e. we're already close to our limits with that.

* turning off nginx, local -> playground: 146/s. Noteworthy: this is the only thing on playground that helped me go
  faster. But we don't actually want to recommend that, of course. Also: this is the only setup where I was able to
  outrun snappea (for a short while). Note that tuning thread for gunicorn / stress-test matters here. (I used 25)

* playground locally w/o nginx and w/ drop-to-floor: 400/s. Noteworthy: very close to what I get on my laptop.



Some conclusions:

* 30/s is still "a lot"; that's 2.5M/day or 77M/month, which is _more_ than the maximum Sentry allows you to select in
  the pricing page. (50M maxes out at $5,795.50 prepaid per month)

* Still, the above raises some questions on "is snappea worth it in this setup". Counterpoints (stability,
  predictability, the fact that there may be other slow async things) still apply.

* I never really got a chance to tune my setup. I did raise gunicorn workers to "enough to deal with the number of
  threads" which was in the 16 - 32 range. But with snappea without a backlog the number of workers is not material to
  the performance.
