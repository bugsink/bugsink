from django.contrib import admin

from .models import AuthToken


@admin.register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "description", "created_at")
    list_filter = ("created_at",)
    ordering = ("-created_at",)
