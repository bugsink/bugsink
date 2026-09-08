from django.contrib import admin

from .models import AuthToken


@admin.register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "description", "is_user_bound", "is_project_bound", "created_at", "expires_at")
    list_filter = ("is_user_bound", "is_project_bound", "created_at", "expires_at")
    ordering = ("-created_at",)

    def has_delete_permission(self, request, obj=None):
        return False
