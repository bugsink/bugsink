import sentry_sdk

sentry_sdk.init(
        dsn=http://06e5fadbb7ee4978a279060331f9997f@localhost:8000/3,
        # capture 100% of transactions for tracing (optional)
        traces_sample_rate=0.0,   # set to 0.0 by default; change if you want performance tracing
        environment=environment,
        release=release,
        # optionally set before_send to filter events
        # before_send=lambda event, hint: event
    )
