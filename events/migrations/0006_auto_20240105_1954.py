from django.db import migrations


def set_event_issue(apps, schema_editor):
    # this was never actually run successfully (the code that ran was a different version), but it's not needed anymore
    # anyway :-) kept for laughs and giggles

    Issue = apps.get_model('issues', 'Issue')

    for issue in Issue.objects.all():
        for event in issue.events.all():
            event.issue = issue
            event.save()


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0005_event_issue'),
        ('issues', '0006_issue_is_muted_and_more'),
    ]

    operations = [
        migrations.RunPython(set_event_issue),
    ]
