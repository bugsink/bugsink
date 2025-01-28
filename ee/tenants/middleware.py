from .base import use_tenant_subdomain


class SelectDatabaseMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        request_subdomain = host.split('.')[0].split(':')[0]

        with use_tenant_subdomain(request_subdomain):
            response = self.get_response(request)

        return response
