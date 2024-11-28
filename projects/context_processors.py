def user_projects_processor(request):
    if not hasattr(request, "user"):
        # check, because if there's a failure "very early" in the request handling, we don't have an AnonymousUser
        return {"user_projects": []}

    if not request.user.is_authenticated:
        return {'user_projects': []}

    return {'user_projects': request.user.project_set.all()}
