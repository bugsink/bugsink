from django.core.management.base import BaseCommand
from django import apps

from bugsink.transaction import durable_atomic


class Command(BaseCommand):

    @durable_atomic
    def handle(self, *args, **options):
        # Copy/paste from bugsink/views's 'def counts' with removal of the limit_runtime / CachedModelCount parts.

        interesting_apps = [
            # "admin",
            # "auth",
            "bsmain",
            # "contenttypes",
            "events",
            "files",
            "ingest",
            "issues",
            # "phonehome",
            "projects",
            "releases",
            # "sessions",
            "snappea",
            "tags",
            "teams",
            "users",
        ]

        counts = {}

        for app_label in interesting_apps:
            counts[app_label] = {}
            app_config = apps.apps.get_app_config(app_label)
            for model in app_config.get_models():
                if model.__name__ == "CachedModelCount":
                    continue  # skip the CachedModelCount model itself

                model_name = f"{app_label}.{model.__name__}"
                print(f"{model_name:<30}{model.objects.count():>12}")
