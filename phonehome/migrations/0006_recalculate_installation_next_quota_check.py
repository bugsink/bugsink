from django.db import migrations
from django.db.models import Sum


def recalculate_installation_next_quota_check(apps, schema_editor):
    # Installation-wide quota checks across projects were incorrect until Bugsink 2.1.1, which means the persisted
    # optimization/state fields may all be wrong. By setting next_quota_check to current_total + 1, we ensure that the
    # very next digested event forces a fresh installation-wide recount under the fixed code. We also reset
    # quota_exceeded_until and quota_exceeded_reason to ensure that the next check is not short-circuited by an
    # incorrect future value of quota_exceeded_until.

    Installation = apps.get_model("phonehome", "Installation")
    Project = apps.get_model("projects", "Project")

    digested_event_count = Project.objects.aggregate(total=Sum("digested_event_count"))["total"] or 0
    Installation.objects.update(
        next_quota_check=digested_event_count + 1,
        quota_exceeded_until=None,
        quota_exceeded_reason="null",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("phonehome", "0005_reset_quota_exceeded_until"),
        ("projects", "0017_project_issue_count"),
    ]

    operations = [
        migrations.RunPython(recalculate_installation_next_quota_check, migrations.RunPython.noop),
    ]
