from celery import shared_task

from projects.models import ProjectMembership
from issues.models import Issue

from .utils import send_rendered_email


def _get_users_for_email_alert(issue):
    # more like memberships as currently implemented :-D
    return ProjectMembership.objects.filter(project=issue.project, send_email_alerts=True).select_related("user")


@shared_task
def send_new_issue_alert(issue_id):
    issue = Issue.objects.get(id=issue_id)
    for membership in _get_users_for_email_alert(issue):
        send_rendered_email(
            subject=f"New issue: {issue.title()}",
            base_template_name="alerts/new_issue",
            recipient_list=[membership.user.email],
            context={
                "issue": issue,
                "project": issue.project,
            },
        )


@shared_task
def send_regression_alert(issue_id):
    raise NotImplementedError("TODO")


@shared_task
def send_unmute_alert(issue_id):
    raise NotImplementedError("TODO")
