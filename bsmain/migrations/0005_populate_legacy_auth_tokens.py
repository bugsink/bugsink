from django.db import migrations


CAPABILITY_FIELDS = (
    "issues_read",
    "events_read",
    "issues_comment",
    "issues_triage",
    "issues_delete",
    "releases_read",
    "releases_create",
    "debug_files_upload",
    "projects_read",
    "projects_manage",
    "teams_read",
    "teams_manage",
)


def populate_legacy_auth_tokens(apps, schema_editor):
    AuthToken = apps.get_model("bsmain", "AuthToken")

    # pre-existing tokens with empty descriptions get a default description
    AuthToken.objects.filter(description="").update(description="Unnamed token")

    # pre-existing tokens get all capabilities enabled (which is what they had before we added the capabilities fields)
    AuthToken.objects.update(
        is_user_bound=False,
        is_project_bound=False,
        expires_at=None,
        user=None,
        project=None,
        **{field_name: True for field_name in CAPABILITY_FIELDS},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("bsmain", "0004_auth_token_capabilities"),
    ]

    operations = [
        migrations.RunPython(populate_legacy_auth_tokens, migrations.RunPython.noop),
    ]
