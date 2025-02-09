from django.utils.html import escape, mark_safe
from django.contrib import admin

import json

from projects.admin import ProjectFilter
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # A note on performance: when using this particular (list) admin on the playground (~150K events), I ran into the
    # fact that it was unusably slow (at least more slow than 30s to render). I examined this for a while, but in the
    # end the conclusion was: "this will simply never work". There's simply too much brokenness here. The admin works
    # fine for the "scaffolding" case, and perhaps for things like users, projects etc, but for the "main event"
    # (events) we'll have to build it ourselves. Regarding the brokenness, some thoughts/links:
    #
    # * arbitrary sorting is (multiple columns) is possible, which means you'll need arbitrary indexes
    # * https://code.djangoproject.com/ticket/8408
    # * https://github.com/django/django/blob/9a3454f6046b/django/contrib/admin/options.py#L1816
    #       no point of configuration for this one, I simply clobbered Django's code directly to turn it off
    # * `actions_selection_counter = False` (possible to set as an admin option)
    # * then I ran into the query itself just being super-slow (presumably caused by sorting)

    # open question: when we'll "build this ourselves", is not some of the sqlite(?) slowness surfacing in other ways?

    ordering = ['-timestamp']

    search_fields = ['event_id', 'debug_info']

    list_display = [
        'timestamp',
        # 'project',
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
        'debug_info',
        'on_site',
    ]

    list_filter = [
        ProjectFilter,
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
    ]

    fields = [
        'id',
        'event_id',
        'ingested_at',
        'digested_at',
        'calculated_type',
        'calculated_value',
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
        'debug_info',
        'pretty_data',
    ]

    readonly_fields = [
        'id',
        'event_id',
        'ingested_at',
        'digested_at',
        'calculated_type',
        'calculated_value',
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
