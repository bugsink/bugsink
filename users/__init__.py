from django.core.checks import Warning, register


@register("users")
def check_single_user_implies_disabled_registration(app_configs, **kwargs):
    from bugsink.app_settings import get_settings
    errors = []
    if get_settings().SINGLE_USER and get_settings().USER_REGISTRATION != "CB_NOBODY":
        errors.append(
            Warning(
                "You're in SINGLE_USER mode, but USER_REGISTRATION is not set to 'CB_NOBODY'. This means that users "
                "can still register, which is probably not what you want.",
                id="users.W001",
            )
        )
    return errors
