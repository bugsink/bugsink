from functools import wraps

from django.shortcuts import get_object_or_404
from django.core.exceptions import PermissionDenied

from projects.models import Project
from issues.models import Issue
from events.models import Event

from .transaction import durable_atomic, immediate_atomic


def login_exempt(view):
    view.login_exempt = True
    return view


def project_membership_required(function):
    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if "project_pk" not in kwargs:
            raise TypeError("project_pk must be passed as a keyword argument")
        project_pk = kwargs.pop("project_pk")
        project = get_object_or_404(Project, pk=project_pk)
        kwargs["project"] = project
        if request.user.is_superuser:
            return function(request, *args, **kwargs)
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
        if request.user.is_superuser:
            return function(request, *args, **kwargs)
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
        if request.user.is_superuser:
            return function(request, *args, **kwargs)
        if event.project.users.filter(pk=request.user.pk).exists():
            return function(request, *args, **kwargs)

        raise PermissionDenied("You don't have permission to access this project")

    return wrapper


def atomic_for_request_method(function, *decorator_args, **decorator_kwargs):
    """
    Wrap the request in the kind of atomic transaction matching its request method:

    ##  for data-altering (POST etc), use immediate_atomic (the desired transaction type for writes)

    This is what immediate_atomic is for.

    ##  for read requests, use the plain old transaction.atomic (with durable=True, to ensure you're the outermost)

    This might be surprising if you think about transactions as mainly a means of guaranteeing atomicity of writes (as
    is directly implied by Django's naming). The thing we're going for is snapshot isolation (given by SQLite in WAL
    mode (which we have turned on) in combination with use of transactions).

    I want to have snapshot isolation because it's a mental model that I can understand. I'd argue it's the natural or
    implicit mental model, and I'd rather have my program behave like so than spend _any_ time thinking about subtleties
    such as "what if you select an event and an issue that are slightly out of sync" or to hunt down any hard to
    reproduce bugs caused by such inconsistencies.

    ## Usage:

    This is provided as a decorator; the expected use case is to wrap an entire view function. The reason is that, in
    practice, reads which should be inside the transaction happen very early, namely when doing the various
    membership_required checks. (the results of these reads are passed into the view function as event/issue/project)

    (Path not taken: one could say that the membership_required tests are separate from the actual handling of the
    request, whether that's a pure display request or an update. Instead of wrapping the transaction around everything,
    you could re-select inside the view function. Potential advantage: shorter transactions (mostly relevant for writes,
    since read-transactions are non-blocking). Disadvantage: one more query, and more complexity)
    """

    @wraps(function)
    def wrapper(request, *args, **kwargs):
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            with immediate_atomic(*decorator_args, **decorator_kwargs):
                return function(request, *args, **kwargs)

        with durable_atomic(*decorator_args, **decorator_kwargs):
            return function(request, *args, **kwargs)

    return wrapper
