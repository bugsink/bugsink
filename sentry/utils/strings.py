from django.utils.encoding import smart_str


def truncatechars(value: str, chars=100):
    """Truncate string and append …"""
    return (value[:chars] + "…") if len(value) > chars else value


def strip(value):
    if not value:
        return ""
    return smart_str(value).strip()
