from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0017_issue_calculated_type_issue_calculated_value'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='ingest_order',
            field=models.PositiveIntegerField(default=123),
            preserve_default=False,
        ),
    ]
