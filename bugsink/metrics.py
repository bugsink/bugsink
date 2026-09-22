from django.db.models import Count

from prometheus_client import Gauge

from issues.models import Issue
from projects.models import Project
from teams.models import Team, TeamMembership


issues_total = Gauge("bugsink_issues_total", "Total number of non-deleted issues.")
projects_total = Gauge("bugsink_projects_total", "Total number of non-deleted projects.")
team_members = Gauge("bugsink_team_members", "Number of accepted team members, per team.", ["team"])
project_issues = Gauge("bugsink_project_issues", "Number of non-deleted issues, per project.", ["project"])


def update_metrics():
    """Recompute all business metrics from the DB; called on every /metrics/ scrape.
    """
    issues_total.set(Issue.objects.filter(is_deleted=False).count())
    projects_total.set(Project.objects.filter(is_deleted=False).count())

    team_members.clear()
    member_counts = dict(TeamMembership.objects.filter(accepted=True).values_list("team__name").annotate(n=Count("id")))
    for team in Team.objects.all():
        team_members.labels(team=team.name).set(member_counts.get(team.name, 0))

    project_issues.clear()
    issue_counts = dict(Issue.objects.filter(is_deleted=False).values_list("project__slug").annotate(n=Count("id")))
    for project in Project.objects.filter(is_deleted=False):
        project_issues.labels(project=project.slug).set(issue_counts.get(project.slug, 0))
