from django.utils.html import escape, mark_safe
from django.contrib import admin

import json

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
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
        'project',
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
        'has_exception',
        'has_logentry',
    ]

    exclude = ["data"]

    readonly_fields = [
        'pretty_data',
    ]

    def pretty_data(self, obj):
        return mark_safe("<pre>" + escape(json.dumps(json.loads(obj.data), indent=2)) + "</pre>")
    pretty_data.short_description = "Data"

    def on_site(self, obj):
        return mark_safe('<a href="' + escape(obj.get_absolute_url()) + '">View</a>')
