### Snappea

I ditched Celery.

Why? It needs a broker. And the broker is "yet another thing to set up". Moving parts are the enemy!
There may still be a future scenario where celery is a choice one can make. I've kept the interface as similar to celery
as I could, so I can have it swapped back in later if needed.

Considered alternatives:

* redislite w/ celery
    this seems "risky", you're basically putting an unsupported part in the (already complicated) machine and hope for
    the best.

* huey with file or sqlite backend?
    the documentation seems to steer one away from this.

* "inside" gunicorn: this didn't seem straightforward at all. uvicorn/channels may be better ways forward, but again,
  the docs are steering one away from this.

For now I'm just running in always-eager mode to facilitate running debugserver. This will probably change at some point.
