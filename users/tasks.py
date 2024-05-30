from django.urls import reverse

from snappea.decorators import shared_task

from bugsink.app_settings import get_settings

from alerts.utils import send_rendered_email


@shared_task
def send_confirm_email(email, token):
    send_rendered_email(
        subject="Confirm your email address",
        base_template_name="users/confirm_email",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "confirm_url": reverse("confirm_email", kwargs={"token": token}),
        },
    )
