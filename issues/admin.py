from django.contrib import admin

from bugsink.transaction import immediate_atomic
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from .models import Issue, Grouping, TurningPoint
from .forms import IssueAdminForm

csrf_protect_m = method_decorator(csrf_protect)


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
    form = IssueAdminForm

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
        'digested_event_count',
        'stored_event_count',
    ]

    inlines = [
        GroupingInline,
        TurningPointInline,
    ]

    list_display = [
        "title",
        "project",
        "digested_event_count",
        "stored_event_count",
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
        'digested_event_count',
        'stored_event_count',
    ]

    def get_deleted_objects(self, objs, request):
        to_delete = list(objs) + ["...all its related objects... (delayed)"]
        model_count = {
            Issue: len(objs),
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
