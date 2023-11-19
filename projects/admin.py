from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'dsn',
    ]
    readonly_fields = [
        'dsn',
    ]
