from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0001_initial'),
        ('issues', '0002_issue_project'),
    ]

    operations = [
        migrations.AlterField(
            model_name='issue',
            name='events',
            field=models.ManyToManyField(to='events.event'),
        ),
    ]
