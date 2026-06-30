from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from bugsink.app_settings import override_settings
from bugsink.test_utils import TransactionTestCase25251 as TransactionTestCase
from projects.models import Project, ProjectMembership, ProjectRole
from teams.models import Team, TeamMembership, TeamRole


User = get_user_model()


class CreateProjectCommandTestCase(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(
            username="admin@example.org",
            email="admin@example.org",
            password="admin",
        )

    def test_creates_team_project_memberships_and_dsn(self):
        stdout = StringIO()

        with override_settings(BASE_URL="http://example.com/base"):
            call_command(
                "create_project",
                "--team",
                "Backend",
                "--project",
                "API",
                "--admin-user",
                "admin@example.org",
                "--project-id",
                "42",
                "--dsn-key",
                "12345678123456781234567812345678",
                stdout=stdout,
            )
            dsn = Project.objects.get().dsn

        team = Team.objects.get()
        project = Project.objects.get()

        self.assertEqual("Backend", team.name)
        self.assertEqual("API", project.name)
        self.assertEqual(42, project.id)
        self.assertEqual("12345678123456781234567812345678", project.sentry_key.hex)

        team_membership = TeamMembership.objects.get(team=team, user=self.admin_user)
        self.assertEqual(TeamRole.ADMIN, team_membership.role)
        self.assertTrue(team_membership.accepted)

        project_membership = ProjectMembership.objects.get(project=project, user=self.admin_user)
        self.assertEqual(ProjectRole.ADMIN, project_membership.role)
        self.assertTrue(project_membership.accepted)

        self.assertEqual("http://12345678123456781234567812345678@example.com/base/42", dsn)
        self.assertIn("DSN: http://12345678123456781234567812345678@example.com/base/42", stdout.getvalue())

    def test_project_id_collision_fails(self):
        Project.objects.create(id=42, name="Existing")

        with self.assertRaisesMessage(CommandError, "Project id is already in use: 42"):
            call_command(
                "create_project",
                "--team",
                "Backend",
                "--project",
                "API",
                "--admin-user",
                "admin@example.org",
                "--project-id",
                "42",
                stdout=StringIO(),
            )

    def test_resets_project_id_sequence_after_manual_id(self):
        call_command(
            "create_project",
            "--team",
            "Backend",
            "--project",
            "API",
            "--admin-user",
            "admin@example.org",
            "--project-id",
            "42",
            stdout=StringIO(),
        )

        next_project = Project.objects.create(name="Next Project")

        self.assertGreater(next_project.id, 42)
