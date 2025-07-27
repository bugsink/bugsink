from django.db import migrations


def delete_objects_pointing_to_null_project(apps, schema_editor):
    # Up until now, we have various models w/ .project=FK(null=True, on_delete=models.SET_NULL)
    # Although it is "not expected" in the interface, project-deletion would have led to those
    # objects with a null project. We're about to change that to .project=FK(null=False, ...) which
    # would crash if we don't remove those objects first. Object-removal is "fine" though, because
    # as per the meaning of the SET_NULL, these objects were "dangling" anyway.

    # We implement this as a _single_ cross-app migration so that reasoning about the order of deletions is easy (and
    # we can just copy the correct order from the project/tasks.py `preferred` variable. This cross-appness does mean
    # that we must specify all dependencies here, and all the set-null migrations (from various apps) must point at this
    # migration as their dependency.

    # from tasks.py, but in "strings" form
    preferred = [
        'tags.EventTag',
        'tags.IssueTag',
        'tags.TagValue',
        'tags.TagKey',
        # 'issues.TurningPoint',  # not needed, .project is already not-null (we just added it)
        'events.Event',
        'issues.Grouping',
        # 'alerts.MessagingServiceConfig',  was CASCADE (not null), so no deletion needed
        # 'projects.ProjectMembership',  was CASCADE (not null), so no deletion needed
        'releases.Release',
        'issues.Issue',
    ]

    for model_name in preferred:
        model = apps.get_model(*model_name.split('.'))
        model.objects.filter(project__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0012_project_is_deleted"),
        ("issues", "0024_turningpoint_project_alter_not_null"),
        ("tags", "0004_alter_do_nothing"),
        ("releases", "0002_release_releases_re_sort_ep_5c07c8_idx"),
        ("events", "0021_alter_do_nothing"),
    ]

    operations = [
        migrations.RunPython(delete_objects_pointing_to_null_project, reverse_code=migrations.RunPython.noop),
    ]
