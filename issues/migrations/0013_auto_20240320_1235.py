import json

from django.db import migrations


def parse_bracketless(s):
    return json.loads(f"[{s}]")


def serialize_lines(l):
    return "".join([e + "\n" for e in l])


def become_line_separated(apps, schema_editor):
    Issue = apps.get_model('issues', 'Issue')

    for issue in Issue.objects.all():
        issue.fixed_at = serialize_lines(parse_bracketless(issue.fixed_at))
        issue.events_at = serialize_lines(parse_bracketless(issue.events_at))
        issue.save()


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0012_auto_20240320_0927'),
    ]

    operations = [
        migrations.RunPython(become_line_separated),
    ]
