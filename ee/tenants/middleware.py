from django.conf import settings
from django.shortcuts import render

from .base import use_tenant_subdomain


class SelectDatabaseMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        request_subdomain = host.split('.')[0].split(':')[0]

        if not request.path.startswith("/static/") and request_subdomain not in settings.TENANTS:
            if hasattr(settings, "TENANTS_STOPPING") and request_subdomain in settings.TENANTS_STOPPING:
                message = "This Hosted Bugsink is no longer available."
            elif hasattr(settings, "TENANTS_MAINTENANCE") and request_subdomain in settings.TENANTS_MAINTENANCE:
                message = "Your Hosted Bugsink is being upgraded. Check again in a moment."
            else:
                message = "Service Unavailable"

            return render(request, "503.html", {"message": message}, status=503)

        with use_tenant_subdomain(request_subdomain):
            response = self.get_response(request)

        return response
