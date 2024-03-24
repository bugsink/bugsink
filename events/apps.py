from django.apps import AppConfig
from django.utils.autoreload import autoreload_started


def watch_for_debugserver_reload(sender, **kwargs):
    from .management.commands.make_consistent import make_consistent
    make_consistent()


class EventsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'events'

    def ready(self):
        autoreload_started.connect(watch_for_debugserver_reload)
