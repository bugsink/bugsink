from django.contrib import admin
from admin_auto_filters.filters import AutocompleteFilter

from .models import Project, ProjectMembership


class ProjectFilter(AutocompleteFilter):
    title = 'Project'
    field_name = 'project'


class UserFilter(AutocompleteFilter):
    title = 'User'
    field_name = 'user'


class ProjectMembershipInline(admin.TabularInline):
    model = ProjectMembership
    autocomplete_fields = [
        'user',
    ]
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    search_fields = [
        'name',
    ]

    list_display = [
        'name',
        'dsn',
        'alert_on_new_issue',
        'alert_on_regression',
        'alert_on_unmute',
    ]

    readonly_fields = [
        'dsn',
    ]

    inlines = [
        ProjectMembershipInline,
    ]
    prepopulated_fields = {
        'slug': ['name'],
    }


# the preferred way to deal with ProjectMembership is actually through the inline above; however, because this may prove
# to not scale well with (very? more than 50?) memberships per project, we've left the separate admin interface here for
# future reference.
@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_filter = [
        ProjectFilter,
        UserFilter,
    ]

    list_display = [
        'project',
        'user',
        'send_email_alerts',
    ]

    autocomplete_fields = [
        'project',
        'user',
    ]
