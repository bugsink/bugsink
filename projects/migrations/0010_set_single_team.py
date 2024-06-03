from django.db import migrations


def set_single_team(apps, schema_editor):
    Team = apps.get_model('teams', 'Team')
    Project = apps.get_model('projects', 'Project')

    team = Team.objects.all().first()  # as created in 0002_create_single_team
    Project.objects.update(team=team)


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0009_project_team'),
        ('teams', '0002_create_single_team'),
    ]

    operations = [
        migrations.RunPython(set_single_team),
    ]
