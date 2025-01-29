from django.db import connection
from django.apps import AppConfig
from django.utils.autoreload import autoreload_started


def watch_for_debugserver_reload(sender, **kwargs):
    return
    from .management.commands.make_consistent import make_consistent
    make_consistent()

    # make_consistent() touches the DB, and we're running this code outside of a request/response cycle (for which the
    # connection is managed by Django), so we need to close the connection manually. (Name of thread: "MainThread")
    connection.close()


class EventsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'events'

    def ready(self):
        autoreload_started.connect(watch_for_debugserver_reload)
