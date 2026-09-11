from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from bugsink.utils import assert_
from events.models import Event
from issues.models import Issue, issue_lookup_kwargs
from projects.models import Project
from releases.models import Release


def enforce_project_boundness(token, project):
    if token.is_project_bound and token.project_id != project.id:
        raise PermissionDenied("This token is not allowed to access this project.")


def _object_from_identifier(object_type, identifier):
    if object_type == "project":
        return get_object_or_404(Project.objects.all(), pk=identifier)
    if object_type == "issue":
        try:
            lookup = issue_lookup_kwargs(identifier)
        except DjangoValidationError:
            raise NotFound()
        return get_object_or_404(Issue.objects.filter(is_deleted=False).select_related("project"), **lookup)
    if object_type == "event":
        return get_object_or_404(Event.objects.select_related("project"), pk=identifier)
    if object_type == "release":
        return get_object_or_404(Release.objects.select_related("project"), pk=identifier)

    raise NotImplementedError("Object lookup not implemented for object type: %s." % object_type)


def _project_for_object(object_type, guarded_object):
    if object_type == "project":
        return guarded_object
    if object_type in ("issue", "release", "event"):
        return guarded_object.project

    raise NotImplementedError("Project lookup not implemented for object type: %s." % object_type)


def resolve_token_guard(view, request, guard, view_kwargs):
    """Resolve a guard's object, enforce the token's project boundary, and return it for injection into the view."""
    object_lookup = guard.lookup
    if object_lookup.using == "url":
        # assert (i.e. programming error guard, not user input) that DRF setup matches the guard's URL keyword
        assert_(object_lookup.key in view_kwargs, (
            '@token_guard on %s.%s expected a URL keyword argument named "%s".'
            % (view.__class__.__name__, view.action, object_lookup.key)
        ))
        guarded_object = _object_from_identifier(guard.object_type, view_kwargs[object_lookup.key])
        injected_kwargs = {}
    elif object_lookup.using == "query":
        identifier = request.query_params.get(object_lookup.key)
        if identifier in (None, ""):
            raise ValidationError({object_lookup.key: ["This field is required."]})
        guarded_object = _object_from_identifier(guard.object_type, identifier)
        injected_kwargs = {}
    elif object_lookup.using == "serializer":
        serializer = view.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        guarded_object = serializer.validated_data[object_lookup.key]
        injected_kwargs = {"serializer": serializer}
    else:
        raise NotImplementedError("Unknown token guard lookup: %s." % object_lookup.using)

    # Preserve DRF's object-permission contract (even though that is presently unused).
    view.check_object_permissions(request, guarded_object)

    project = _project_for_object(guard.object_type, guarded_object)
    enforce_project_boundness(request.auth, project)

    injected_kwargs[guard.object_type] = guarded_object
    return injected_kwargs
