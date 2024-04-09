from django.db import migrations
from django.utils.text import slugify


def set_project_slugs(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    for project in Project.objects.all():
        project.slug = slugify(project.name)
        project.save()


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_project_slug'),
    ]

    operations = [
        migrations.RunPython(set_project_slugs),
    ]
