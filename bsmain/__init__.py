import urllib.parse

from django.core.checks import Warning, register
from django.conf import settings

from bugsink.app_settings import get_settings
from events.storage_registry import get_write_storage


@register("bsmain")
def check_no_nested_settings_in_unnested_form(app_configs, **kwargs):
    errors = []
    for key in get_settings().keys():
        if hasattr(settings, key):
            errors.append(Warning(
                f"The setting {key} is defined at the top level of your configuration. It must be nested under the "
                f"'BUGSINK' setting.",
                id="bsmain.W001",
            ))
    return errors


@register("bsmain")
def check_event_storage_properly_configured(app_configs, **kwargs):
    errors = []
    try:
        #  rather than doing an explicit check, we just run the `get_write_storage` code and see if it throws an error
        # get_write_storage() touches the whole storage system, so if it fails, we know something is wrong
        get_write_storage()
    except ValueError as e:
        errors.append(Warning(
            str(e),
            id="bsmain.W002",
            ))
    return errors


@register("bsmain")
def check_base_url_is_url(app_configs, **kwargs):
    try:
        parts = urllib.parse.urlsplit(get_settings().BASE_URL)
    except ValueError as e:
        return [Warning(
            str(e),
            id="bsmain.W003",
        )]

    if parts.scheme not in ["http", "https"]:
        return [Warning(
            "The BASE_URL setting must be a valid URL (starting with http or https).",
            id="bsmain.W003",
        )]

    if not parts.hostname:
        return [Warning(
            "The BASE_URL setting must be a valid URL. The hostname must be set.",
            id="bsmain.W003",
        )]

    return []
