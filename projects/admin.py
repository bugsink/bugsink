from django.contrib import admin

from .models import Project, ProjectMembership


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'dsn',
    ]
    readonly_fields = [
        'dsn',
    ]


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = [
        'project',
        'user',
    ]
