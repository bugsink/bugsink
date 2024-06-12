from django.test import TestCase as DjangoTestCase

from django.core import mail
from django.contrib.auth import get_user_model
from django.template.loader import get_template

from issues.factories import get_or_create_issue
from projects.models import Project, ProjectMembership
from events.factories import create_event

from .tasks import send_new_issue_alert, send_regression_alert, send_unmute_alert
from .views import DEBUG_CONTEXTS

User = get_user_model()


class TestAlertSending(DjangoTestCase):

    def test_send_new_issue_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_new_issue_alert(issue.id)

        self.assertEqual(len(mail.outbox), 1)

    def test_send_regression_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_regression_alert(issue.id)

        self.assertEqual(len(mail.outbox), 1)

    def test_send_unmute_alert(self):
        project = Project.objects.create(name="Test project")

        user = User.objects.create_user(username="testuser", email="test@example.org")
        ProjectMembership.objects.create(
            project=project,
            user=user,
            send_email_alerts=True,
        )

        issue, _ = get_or_create_issue(project=project)
        create_event(project=project, issue=issue)

        send_unmute_alert(issue.id, "Some unumte reason")

        self.assertEqual(len(mail.outbox), 1)

    def test_txt_and_html_have_relevant_variables_defined(self):
        example_context = DEBUG_CONTEXTS["issue_alert"]
        html_template = get_template("mails/issue_alert.html")
        text_template = get_template("mails/issue_alert.txt")

        unused_in_text = [
            "base_url",  # link to the site is not included at the top of the text template
        ]

        for type_, template in [("html", html_template), ("text", text_template)]:
            for variable in example_context.keys():
                if type_ == "text" and variable in unused_in_text:
                    continue

                self.assertTrue(
                    "{{ %s" % variable in template.template.source, "'{{ %s ' not in %s template" % (variable, type_))
