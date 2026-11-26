from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils import timezone

from bugsink.app_settings import get_settings


def deactivate_existing_users(apps, schema_editor):
    User = apps.get_model("users", "User")
    EmailVerification = apps.get_model("users", "EmailVerification")
    TeamMembership = apps.get_model("teams", "TeamMembership")
    ProjectMembership = apps.get_model("projects", "ProjectMembership")
    AuthToken = apps.get_model("bsmain", "AuthToken")
    database = schema_editor.connection.alias

    cutoff = timezone.now() - timedelta(seconds=get_settings().USER_REGISTRATION_VERIFY_EMAIL_EXPIRY)
    # MySQL cannot update auth_user while selecting from it in a subquery.
    pending_user_ids = list(User.objects.using(database).filter(
        is_active=False,
        last_login__isnull=True,
        date_joined__gte=cutoff,
        is_superuser=False,
        is_staff=False,
        emailverification__created_at__gte=cutoff,
    ).values_list("pk", flat=True))
    User.objects.using(database).filter(is_active=False).exclude(pk__in=pending_user_ids).update(
        is_deactivated=True, is_superuser=False, is_staff=False, password=make_password(None))

    deactivated_users = User.objects.using(database).filter(is_deactivated=True)
    TeamMembership.objects.using(database).filter(user__in=deactivated_users).delete()
    ProjectMembership.objects.using(database).filter(user__in=deactivated_users).delete()
    EmailVerification.objects.using(database).filter(user__in=deactivated_users).delete()
    AuthToken.objects.using(database).filter(user__in=deactivated_users, is_user_bound=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_user_is_deactivated"),
        ("bsmain", "0005_populate_legacy_auth_tokens"),
        ("projects", "0019_alter_project_name_and_more"),
        ("teams", "0002_team_teams_team_name_43e047_idx"),
    ]

    operations = [
        migrations.RunPython(deactivate_existing_users, migrations.RunPython.noop),
    ]
