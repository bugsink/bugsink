import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection

from bugsink.transaction import immediate_atomic
from projects.models import Project, ProjectMembership, ProjectRole
from teams.models import Team, TeamMembership, TeamRole


User = get_user_model()


def parse_project_id(value):
    if value is None:
        return None

    try:
        project_id = int(value)
    except ValueError as e:
        raise CommandError("--project-id should be a positive integer") from e

    if project_id <= 0:
        raise CommandError("--project-id should be a positive integer")

    return project_id


def parse_sentry_key(value):
    if value is None:
        return uuid.uuid4()

    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise CommandError("--dsn-key should be a UUID or 32 hex characters") from e


def reset_project_id_sequence():
    statements = connection.ops.sequence_reset_sql(no_style(), [Project])
    if not statements:
        return

    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class Command(BaseCommand):
    help = "Create a team, project, memberships, and DSN for an existing admin user."

    def add_arguments(self, parser):
        parser.add_argument("--team", required=True, help="Team name to create or reuse.")
        parser.add_argument("--project", required=True, help="Project name to create.")
        parser.add_argument("--admin-user", required=True, help="Username of the user who should administer both.")
        parser.add_argument("--project-id", help="Optional project id to use in the DSN.")
        parser.add_argument("--dsn-key", help="Optional DSN public key as a UUID or 32 hex characters.")

    def handle(self, *args, **options):
        project_id = parse_project_id(options["project_id"])
        sentry_key = parse_sentry_key(options["dsn_key"])

        with immediate_atomic():
            try:
                admin_user = User.objects.get(username=options["admin_user"])
            except User.DoesNotExist as e:
                raise CommandError("Admin user does not exist: %s" % options["admin_user"]) from e

            if project_id is not None and Project.objects.filter(id=project_id).exists():
                raise CommandError("Project id is already in use: %s" % project_id)

            if Project.objects.filter(name=options["project"]).exists():
                raise CommandError("Project name is already in use: %s" % options["project"])

            team, _ = Team.objects.get_or_create(name=options["team"])
            team_membership, _ = TeamMembership.objects.get_or_create(
                team=team,
                user=admin_user,
                defaults={"role": TeamRole.ADMIN, "accepted": True},
            )
            if team_membership.role != TeamRole.ADMIN or not team_membership.accepted:
                team_membership.role = TeamRole.ADMIN
                team_membership.accepted = True
                team_membership.save(update_fields=["role", "accepted"])

            project = Project.objects.create(
                id=project_id,
                team=team,
                name=options["project"],
                sentry_key=sentry_key,
            )
            ProjectMembership.objects.create(
                project=project,
                user=admin_user,
                role=ProjectRole.ADMIN,
                accepted=True,
            )

            if project_id is not None:
                reset_project_id_sequence()

        self.stdout.write("Team: %s" % team.name)
        self.stdout.write("Project: %s" % project.name)
        self.stdout.write("DSN: %s" % project.dsn)
