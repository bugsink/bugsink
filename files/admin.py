from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Chunk, File, FileMetadata


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ('checksum', 'size')
    search_fields = ('checksum',)
    readonly_fields = ('data',)


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('filename', 'checksum', 'size', 'download_link')
    search_fields = ('checksum',)
    readonly_fields = ('data', 'download_link')

    def download_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("download_file", args=(obj.checksum,)), str(obj.filename),
        )


@admin.register(FileMetadata)
class FileMetadataAdmin(admin.ModelAdmin):
    list_display = ('debug_id', 'file_type', 'file')
    search_fields = ('file__checksum', 'debug_id', 'file_type')
