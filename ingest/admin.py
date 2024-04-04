from django.utils.html import escape, mark_safe
from django.contrib import admin

import json

from projects.admin import ProjectFilter
from .models import DecompressedEvent


@admin.register(DecompressedEvent)
class DecompressedEventAdmin(admin.ModelAdmin):
    ordering = ['-timestamp']

    list_filter = [
        ProjectFilter,
    ]

    list_display = [
        "timestamp",
        "project",
    ]

    exclude = ["data"]

    readonly_fields = [
        'project',
        'pretty_data',
    ]

    def pretty_data(self, obj):
        return mark_safe("<pre>" + escape(json.dumps(json.loads(obj.data), indent=2)) + "</pre>")
    pretty_data.short_description = "Data"
