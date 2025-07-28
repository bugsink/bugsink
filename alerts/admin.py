from django.contrib import admin

from .models import MessagingServiceConfig


@admin.register(MessagingServiceConfig)
class MessagingServiceConfigAdmin(admin.ModelAdmin):
    list_display = ('project', 'display_name', 'kind', 'last_failure_timestamp')
    search_fields = ('name', 'service_type')
    list_filter = ('kind',)
