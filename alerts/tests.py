from django.test import TestCase as DjangoTestCase

from django.core import mail
from django.contrib.auth import get_user_model
from django.template.loader import get_template

from issues.factories import get_or_create_issue
from projects.models import Project, ProjectMembership
from events.factories import create_event
from teams.models import Team, TeamMembership

from .tasks import send_new_issue_alert, send_regression_alert, send_unmute_alert, _get_users_for_email_alert
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

    def test_get_users_for_email_alert(self):
        team = Team.objects.create(name="Test team")
        project = Project.objects.create(name="Test project", team=team)
        user = User.objects.create_user(username="testuser", email="test@example.org", send_email_alerts=True)
        issue, _ = get_or_create_issue(project=project)

        # no ProjectMembership, user should not be included
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # ProjectMembership w/ send=False, should not be included
        pm = ProjectMembership.objects.create(project=project, user=user, send_email_alerts=False)
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # ProjectMembership w/ send=True, should be included
        pm.send_email_alerts = True
        pm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # Set send=None, fall back to User (which has True)
        pm.send_email_alerts = None
        pm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # (User has False)
        user.send_email_alerts = False
        user.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Insert TeamMembership - this provides an intermediate layer of configuration between User and
        # ProjectMembership; we start with send=True at the tm level and expect the user to be included
        tm = TeamMembership.objects.create(team=team, user=user, send_email_alerts=True)
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])

        # Set send=False at the tm level, user should not be included
        tm.send_email_alerts = False
        tm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Set send=None at the tm level, back to the user level (which is False)
        tm.send_email_alerts = None
        tm.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [])

        # Set send=True at the user level, user should be included
        user.send_email_alerts = True
        user.save()
        self.assertEqual(list(_get_users_for_email_alert(issue)), [user])
