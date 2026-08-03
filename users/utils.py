from bugsink.app_settings import get_settings


def normalize_email(email):
    """Lowercase `email` when the instance is configured to treat emails case-insensitively."""
    if email and get_settings().USER_EMAIL_CASE_INSENSITIVE:
        return email.lower()
    return email

