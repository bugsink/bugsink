from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0020_alter_issue_unique_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='last_frame_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='issue',
            name='last_frame_function',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='issue',
            name='last_frame_module',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='issue',
            name='transaction',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
