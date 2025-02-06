from django.core.management.base import BaseCommand
from django.core.management import call_command

from issues.models import Issue
from events.models import Event


class Command(BaseCommand):
    help = "..."

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        if input("Clean slate (ingestion and its effect)? [y/n] ") != "y":
            return

        print("nuking")
        Issue.objects.all().delete()
        Event.objects.all().delete()

        call_command("make_consistent")
