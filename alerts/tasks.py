from celery import shared_task

from django.conf import settings
from django.template.defaultfilters import truncatechars

from projects.models import ProjectMembership

from .utils import send_rendered_email


def _get_users_for_email_alert(issue):
    # more like memberships as currently implemented :-D
    return ProjectMembership.objects.filter(project=issue.project, send_email_alerts=True).select_related("user")


@shared_task
def send_new_issue_alert(issue_id):
    _send_alert(issue_id, "New issue:", "a", "NEW")


@shared_task
def send_regression_alert(issue_id):
    _send_alert(issue_id, "Regression:", "a", "REGRESSED")


@shared_task
def send_unmute_alert(issue_id):
    _send_alert(issue_id, "Unmuted issue:", "an", "UNMUTED")


def _send_alert(issue_id, subject_prefix, alert_article, alert_reason):
    from issues.models import Issue  # avoid circular import

    issue = Issue.objects.get(id=issue_id)
    for membership in _get_users_for_email_alert(issue):
        send_rendered_email(
            subject=truncatechars(f"{subject_prefix} {issue.title()} in {issue.project.name}", 100),
            base_template_name="alerts/issue_alert",
            recipient_list=[membership.user.email],
            context={
                "site_title": settings.SITE_TITLE,
                "base_url": settings.BASE_URL + "/",
                "issue_title": issue.title(),
                "project_name": issue.project.name,
                "issue_url": settings.BASE_URL + issue.get_absolute_url(),
                "alert_article": alert_article,
                "alert_reason": alert_reason,
                "settings_url": settings.BASE_URL + "/",  # TODO
            },
        )
