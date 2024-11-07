from django.contrib import admin

from .models import OutboundMessage


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("attempted_at", "sent_at")
    readonly_fields = ("attempted_at", "sent_at", "message")
