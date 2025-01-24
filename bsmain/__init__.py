from django.core.checks import Warning, register
from django.conf import settings

from bugsink.app_settings import get_settings


@register("bsmain")
def check_no_nested_settings_in_unnested_form(app_configs, **kwargs):
    errors = []
    for key in get_settings().keys():
        if hasattr(settings, key):
            errors.append(Warning(
                f"The setting {key} is defined at the top level of your configuration. It must be nested under the "
                f"'BUGSINK' setting."
            ))
    return errors
