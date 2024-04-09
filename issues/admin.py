from django.contrib import admin

from .models import Issue, Grouping


class GroupingInline(admin.TabularInline):
    model = Grouping
    extra = 0
    exclude = ['project']
    readonly_fields = [
        'grouping_key',
    ]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    fields = [
        'project',
        'friendly_id',
        'calculated_type',
        'calculated_value',
        'last_seen',
        'first_seen',
        'is_resolved',
        'fixed_at',
        'events_at',
        'is_muted',
        'unmute_on_volume_based_conditions',
        'unmute_after',
        'event_count',
    ]

    inlines = [
        GroupingInline,
    ]

    list_display = [
        "title",
        "project",
        "event_count",
    ]
    list_filter = [
        "project",
    ]

    exclude = ["events"]

    readonly_fields = [
        'project',
        'friendly_id',
        'calculated_type',
        'calculated_value',
        'event_count',
    ]
