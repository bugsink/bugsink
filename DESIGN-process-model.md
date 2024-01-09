

Just a few thoughts on the model we use for multi-processes, multi-threads, and how this relates to DB locks.


Basic idea: if we run a single (gunicorn) process, locks can't ever become a problem.


### Celery

For now, we use Celery.
It's the most out-of-the-box solution for async stuff (which we need for e.g. emails)

I wonder if we'll still use this once we do a serious cutting up between ingest/digest, but we'll cross that bridge when
we get there.

For now I'm just running in always-eager mode to facilitate running debugserver. This will probably change at some point.

If you'd need a worker, this is how you'd start it:

```
celery -A bugsink worker -l INFO
```

(I wonder: if single-worker is such a key concept, this may need to be applied on celery too... but that depends
entirely on what we let celery do)
