from django.utils.html import escape, mark_safe
from django.contrib import admin

import json

from projects.admin import ProjectFilter
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    ordering = ['-timestamp']

    list_display = [
        'timestamp',
        # 'project',
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
        'has_exception',
        'has_logentry',
        'debug_info',
        'on_site',
    ]

    list_filter = [
        ProjectFilter,
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
        'has_exception',
        'has_logentry',
    ]

    fields = [
        'id',
        'event_id',
        'ingested_event',
        'server_side_timestamp',
        'issue',
        'project',
        'timestamp',
        'platform',
        'level',
        'logger',
        'transaction',
        'server_name',
        'release',
        'dist',
        'environment',
        'sdk_name',
        'sdk_version',
        'has_exception',
        'has_logentry',
        'debug_info',
        'pretty_data',
    ]

    readonly_fields = [
        'id',
        'event_id',
        'ingested_event',
        'server_side_timestamp',
        'issue',
        'timestamp',
        'project',
        'pretty_data',
    ]

    def pretty_data(self, obj):
        return mark_safe("<pre>" + escape(json.dumps(json.loads(obj.data), indent=2)) + "</pre>")
    pretty_data.short_description = "Data"

    def on_site(self, obj):
        return mark_safe('<a href="' + escape(obj.get_absolute_url()) + '">View</a>')
