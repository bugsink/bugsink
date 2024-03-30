import os

from django.core.management.base import BaseCommand

from events.models import Event


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('path', type=str)
        parser.add_argument('--project_id', type=int)

    def handle(self, *args, **options):
        path = options['path']
        project_id = options['project_id']

        events = Event.objects.all()
        if project_id:
            events = events.filter(project_id=project_id)

        for event in events:
            with open(os.path.join(path, f'{event.event_id}.json'), 'w') as f:
                f.write(event.data)
