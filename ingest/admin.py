from django.contrib import admin

from .models import Envelope


@admin.register(Envelope)
class EnvelopeAdmin(admin.ModelAdmin):
    list_display = ("id", "project_pk", "ingested_at")
    fields = ["project_pk", "ingested_at", "data"]
    readonly_fields = ["project_pk", "ingested_at", "data"]
