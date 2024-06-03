from django.db import migrations


def create_single_team(apps, schema_editor):
    # if needed (for existing projects); this should not be preserved when we squash/restart migrations

    Project = apps.get_model('projects', 'Project')
    Team = apps.get_model('teams', 'Team')

    if Project.objects.count() == 0:
        return

    Team.objects.create(name='Single Team', slug='single-team')


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0001_initial'),
        ('projects', '0008_set_project_slugs'),
    ]

    operations = [
        migrations.RunPython(create_single_team),
    ]
