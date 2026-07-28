from django.core.checks import Error, register
from django.contrib.auth import get_user_model
from django.db import connection

from bugsink.app_settings import get_settings


@register("users")
def check_emails_are_lowercase(app_configs, **kwargs):
    """USER_EMAIL_CASE_INSENSITIVE lowercases emails on the way in; pre-existing mixed-case users can no longer log
    in (nor reset their password) until their stored username is lowercased too."""

    if not get_settings().USER_EMAIL_CASE_INSENSITIVE:
        return []

    User = get_user_model()
    if User._meta.db_table not in connection.introspection.table_names():
        return []  # not migrated yet; there are no users to be locked out

    usernames = [u for u in User.objects.values_list("username", flat=True) if u != u.lower()]
    if not usernames:
        return []

    examples = ", ".join(sorted(usernames)[:3]) + (", ..." if len(usernames) > 3 else "")
    return [Error(
        f"USER_EMAIL_CASE_INSENSITIVE is on, but {len(usernames)} user(s) still have a mixed-case email "
        f"({examples}). They cannot log in or reset their password. Run 'bugsink-manage lowercase_user_emails' "
        f"(or turn the setting back off).",
        id="users.E001",
    )]

