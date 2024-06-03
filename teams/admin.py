from django.contrib import admin
from admin_auto_filters.filters import AutocompleteFilter

from .models import Team, TeamMembership


class TeamFilter(AutocompleteFilter):
    title = 'Team'
    field_name = 'team'


class UserFilter(AutocompleteFilter):
    title = 'User'
    field_name = 'user'


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    autocomplete_fields = [
        'user',
    ]
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    search_fields = [
        'name',
    ]

    list_display = [
        'name',
    ]

    readonly_fields = [
    ]

    inlines = [
        TeamMembershipInline,
    ]


# the preferred way to deal with TeamMembership is actually through the inline above; however, because this may prove
# to not scale well with (very? more than 50?) memberships per team, we've left the separate admin interface here for
# future reference.
@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_filter = [
        TeamFilter,
        UserFilter,
    ]

    list_display = [
        'team',
        'user',
    ]

    autocomplete_fields = [
        'team',
        'user',
    ]
