from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_set_project_slugs'),
        ('issues', '0019_set_ingest_order'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='issue',
            unique_together={('project', 'ingest_order')},
        ),
    ]
