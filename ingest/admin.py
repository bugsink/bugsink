from django.contrib import admin

from .models import DecompressedEvent


@admin.register(DecompressedEvent)
class DecompressedEventAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "project"]
