import json

from django.utils.html import escape, mark_safe
from django.contrib import admin
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator

from bugsink.transaction import immediate_atomic

from projects.admin import ProjectFilter
from .models import Event

csrf_protect_m = method_decorator(csrf_protect)


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

    search_fields = ['event_id']

    list_display = [
        'timestamp',
        # 'project',
        'platform',
        'level',
        'sdk_name',
        'sdk_version',
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

    def get_deleted_objects(self, objs, request):
        to_delete = list(objs) + ["...all its related objects... (delayed)"]
        model_count = {
            Event: len(objs),
        }
        perms_needed = set()
        protected = []
        return to_delete, model_count, perms_needed, protected

    def delete_queryset(self, request, queryset):
        # NOTE: not the most efficient; it will do for a first version.
        with immediate_atomic():
            for obj in queryset:
                obj.delete_deferred()

    def delete_model(self, request, obj):
        with immediate_atomic():
            obj.delete_deferred()

    @csrf_protect_m
    def delete_view(self, request, object_id, extra_context=None):
        # the superclass version, but with the transaction.atomic context manager commented out (we do this ourselves)
        # with transaction.atomic(using=router.db_for_write(self.model)):
        return self._delete_view(request, object_id, extra_context)
