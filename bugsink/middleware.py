from django.contrib.auth.decorators import login_required


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            return

        # we explicitly ignore the admin and accounts paths, and the api; we can always push this to a setting later
        for path in ["/admin", "/accounts", "/api"]:
            if request.path.startswith(path):
                return None  # returning None is interpreted by Django as "proceed with handling it"

        if getattr(view_func, 'login_exempt', False):
            return None

        return login_required(view_func)(request, *view_args, **view_kwargs)
