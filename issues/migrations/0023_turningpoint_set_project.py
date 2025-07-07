from django.db import migrations


def turningpoint_set_project(apps, schema_editor):
    TurningPoint = apps.get_model("issues", "TurningPoint")

    # TurningPoint.objects.update(project=F("issue__project"))
    # fails with 'Joined field references are not permitted in this query"

    # This one's elegant and works in sqlite but not in MySQL:
    # TurningPoint.objects.update(
    #     project=Subquery(
    #         TurningPoint.objects
    #             .filter(pk=OuterRef('pk'))
    #             .values('issue__project')[:1]
    #     )
    # )
    # django.db.utils.OperationalError: (1093, "You can't specify target table 'issues_turningpoint' for update in FROM
    # clause")

    # so in the end we'll just loop:

    for turningpoint in TurningPoint.objects.all():
        turningpoint.project = turningpoint.issue.project
        turningpoint.save(update_fields=["project"])


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0022_turningpoint_project"),
    ]

    operations = [
        migrations.RunPython(turningpoint_set_project, migrations.RunPython.noop),
    ]
