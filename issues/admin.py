from django.contrib import admin

from .models import Issue


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = [
        "hash",
        "event_count",  # expensive operation as written now (query in loop)
    ]
    exclude = ["events"]

    readonly_fields = [
        'event_count',
    ]

    def event_count(self, obj):
        return str(obj.events.count())
    event_count.short_description = "Event count"
