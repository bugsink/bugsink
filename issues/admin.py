from django.contrib import admin

from .models import Issue, Grouping, TurningPoint


class GroupingInline(admin.TabularInline):
    model = Grouping
    extra = 0
    exclude = ['project']
    readonly_fields = [
        'grouping_key',
    ]


class TurningPointInline(admin.TabularInline):
    model = TurningPoint
    extra = 0
    exclude = ['project']
    fields = [
        "kind",
        "timestamp",
        "user",
        "triggering_event",
        "metadata",
        "comment",
    ]
    readonly_fields = [
        "user",  # readonly because it avoid thinking about well-implemented select-boxes
        "triggering_event",  # readonly because it avoid thinking about well-implemented select-boxes
        "metadata",  # readonly to avoid a big textbox
        "comment",  # readonly to avoid a big textbox
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
        TurningPointInline,
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
