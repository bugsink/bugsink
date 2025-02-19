from django.urls import reverse

from snappea.decorators import shared_task

from bugsink.app_settings import get_settings
from bugsink.utils import send_rendered_email


@shared_task
def send_confirm_email(email, token):
    send_rendered_email(
        subject="Confirm your email address",
        base_template_name="mails/confirm_email",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "confirm_url": get_settings().BASE_URL + reverse("confirm_email", kwargs={"token": token}),
        },
    )


@shared_task
def send_reset_email(email, token):
    send_rendered_email(
        subject="Reset your password",
        base_template_name="mails/reset_password_email",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "reset_url": get_settings().BASE_URL + reverse("reset_password", kwargs={"token": token}),
        },
    )


@shared_task
def send_welcome_email(email, token, reason):
    send_rendered_email(
        subject="Welcome to Bugsink",
        base_template_name="mails/welcome_email",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "reset_url": get_settings().BASE_URL + reverse("reset_password", kwargs={"token": token}),
            "reason": reason,
        },
    )
