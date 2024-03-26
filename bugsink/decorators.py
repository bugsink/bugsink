from functools import wraps

from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied

from projects.models import Project
from issues.models import Issue
from events.models import Event


def login_exempt(view):
    view.login_exempt = True
    return view


def project_membership_required(function):
    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if "project_id" not in kwargs:
            raise TypeError("project_id must be passed as a keyword argument")
        project_id = kwargs.pop("project_id")
        project = get_object_or_404(Project, pk=project_id)
        kwargs["project"] = project
        if project.users.filter(pk=request.user.pk).exists():
            return function(request, *args, **kwargs)

        raise PermissionDenied("You don't have permission to access this project")

    return wrapper


def issue_membership_required(function):
    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if "issue_pk" not in kwargs:
            raise TypeError("issue_pk must be passed as a keyword argument")
        issue_pk = kwargs.pop("issue_pk")
        issue = get_object_or_404(Issue, pk=issue_pk)
        kwargs["issue"] = issue
        if issue.project.users.filter(pk=request.user.pk).exists():
            return function(request, *args, **kwargs)

        raise PermissionDenied("You don't have permission to access this project")

    return wrapper


def event_membership_required(function):
    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if "event_pk" not in kwargs:
            raise TypeError("event_pk must be passed as a keyword argument")
        event_pk = kwargs.pop("event_pk")
        event = get_object_or_404(Event, pk=event_pk)
        kwargs["event"] = event
        if event.project.users.filter(pk=request.user.pk).exists():
            return function(request, *args, **kwargs)

        raise PermissionDenied("You don't have permission to access this project")

    return wrapper
