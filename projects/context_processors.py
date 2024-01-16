def user_projects_processor(request):
    if not request.user.is_authenticated:
        return {
            'user_projects': [],
        }

    return {
        'user_projects': request.user.project_set.all(),
    }
