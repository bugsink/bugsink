from django.db import migrations


def migrate_empty_fixed_at(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")

    for issue in Issue.objects.filter(fixed_at__contains="\n"):
        fixed_at = issue.fixed_at.split("\n")[:-1]
        if "" not in fixed_at:
            continue

        issue.fixed_at = "".join(release + "\n" for release in fixed_at if release != "")
        if issue.is_resolved and not issue.is_resolved_by_next_release:
            issue.is_resolved_unconditionally = True
        issue.save(update_fields=["fixed_at", "is_resolved_unconditionally"])


def unmigrate_empty_fixed_at(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")

    for issue in Issue.objects.filter(is_resolved_unconditionally=True):
        fixed_at = issue.fixed_at.split("\n")[:-1]
        if "" not in fixed_at:
            fixed_at.append("")
            issue.fixed_at = "".join(release + "\n" for release in fixed_at)
            issue.save(update_fields=["fixed_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("issues", "0027_issue_is_resolved_unconditionally"),
    ]

    operations = [
        migrations.RunPython(migrate_empty_fixed_at, unmigrate_empty_fixed_at),
    ]
