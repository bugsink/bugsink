from django.urls import reverse

from snappea.decorators import shared_task

from bugsink.app_settings import get_settings
from bugsink.utils import send_rendered_email

from .models import Team


@shared_task
def send_team_invite_email_new_user(email, team_pk, token):
    team = Team.objects.get(pk=team_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % team.name,
        base_template_name="mails/team_membership_invite_new_user",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "team_name": team.name,
            "url": get_settings().BASE_URL + reverse("team_members_accept_new_user", kwargs={
                "token": token,
                "team_pk": team_pk,
            }),
        },
    )


@shared_task
def send_team_invite_email(email, team_pk):
    team = Team.objects.get(pk=team_pk)

    send_rendered_email(
        subject='You have been invited to join "%s"' % team.name,
        base_template_name="mails/team_membership_invite",
        recipient_list=[email],
        context={
            "site_title": get_settings().SITE_TITLE,
            "base_url": get_settings().BASE_URL + "/",
            "team_name": team.name,
            "url": get_settings().BASE_URL + reverse("team_members_accept", kwargs={
                "team_pk": team_pk,
            }),
        },
    )
