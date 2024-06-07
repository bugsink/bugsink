from django.urls import reverse

from snappea.decorators import shared_task

from bugsink.app_settings import get_settings
from bugsink.utils import send_rendered_email

from .models import Project


@shared_task
def send_project_invite_email_new_user(email, project_pk, token):
    project = Project.objects.get(pk=project_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % project.name,
        base_template_name="mails/project_membership_invite_new_user",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "project_name": project.name,
            "url": get_settings().BASE_URL + reverse("project_members_accept_new_user", kwargs={
                "token": token,
                "project_pk": project_pk,
            }),
        },
    )


@shared_task
def send_project_invite_email(email, project_pk):
    project = Project.objects.get(pk=project_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % project.name,
        base_template_name="mails/project_membership_invite",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "project_name": project.name,
            "url": get_settings().BASE_URL + reverse("project_members_accept", kwargs={
                "project_pk": project_pk,
            }),
        },
    )
