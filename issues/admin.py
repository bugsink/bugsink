from django.contrib import admin

from .models import Issue


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    fields = [
        'project',
        'hash',
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

    list_display = [
        "title",
        "hash",
        "project",
        "event_count",  # expensive operation as written now (query in loop)
    ]
    list_filter = [
        "project",
    ]

    exclude = ["events"]

    readonly_fields = [
        'project',
        'event_count',
    ]

    def event_count(self, obj):
        return str(obj.event_set.count())
    event_count.short_description = "Event count"
