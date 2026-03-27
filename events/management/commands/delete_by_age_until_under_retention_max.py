from django.core.management.base import BaseCommand
from events.tasks import delete_by_age_until_under_retention_max
from projects.models import Project


class Command(BaseCommand):

    def handle(self, *args, **options):
        for project in Project.objects.all():
            if project.stored_event_count > project.get_retention_max_event_count():
                delete_by_age_until_under_retention_max.delay(project.id)
