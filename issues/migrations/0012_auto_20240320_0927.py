from django.db import migrations


def become_bracketless(apps, schema_editor):
    Issue = apps.get_model('issues', 'Issue')

    for issue in Issue.objects.all():
        issue.fixed_at = issue.fixed_at[1:-1]
        issue.events_at = issue.events_at[1:-1]
        issue.save()


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0011_alter_issue_events_at_alter_issue_fixed_at'),
    ]

    operations = [
        migrations.RunPython(become_bracketless)
    ]
