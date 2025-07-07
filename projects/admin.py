from django.contrib import admin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from admin_auto_filters.filters import AutocompleteFilter

from bugsink.transaction import immediate_atomic

from .models import Project, ProjectMembership


csrf_protect_m = method_decorator(csrf_protect)


class ProjectFilter(AutocompleteFilter):
    title = 'Project'
    field_name = 'project'


class UserFilter(AutocompleteFilter):
    title = 'User'
    field_name = 'user'


class ProjectMembershipInline(admin.TabularInline):
    model = ProjectMembership
    autocomplete_fields = [
        'user',
    ]
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    search_fields = [
        'name',
    ]

    list_display = [
        'name',
        'dsn',
        'digested_event_count',
        'stored_event_count',
    ]

    readonly_fields = [
        'dsn',
    ]

    inlines = [
        ProjectMembershipInline,
    ]
    prepopulated_fields = {
        'slug': ['name'],
    }

    def get_deleted_objects(self, objs, request):
        to_delete = list(objs) + ["...all its related objects... (delayed)"]
        model_count = {
            Project: len(objs),
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


# the preferred way to deal with ProjectMembership is actually through the inline above; however, because this may prove
# to not scale well with (very? more than 50?) memberships per project, we've left the separate admin interface here for
# future reference.
@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_filter = [
        ProjectFilter,
        UserFilter,
    ]

    list_display = [
        'project',
        'user',
        'send_email_alerts',
    ]

    autocomplete_fields = [
        'project',
        'user',
    ]
