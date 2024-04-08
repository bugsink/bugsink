from django.utils.encoding import smart_str


def strip(value):
    if not value:
        return ""
    return smart_str(value).strip()
