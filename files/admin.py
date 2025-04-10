from django.contrib import admin
from .models import Chunk, File, FileMetadata


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ('checksum', 'size')
    search_fields = ('checksum',)
    readonly_fields = ('data',)


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('checksum', 'size')
    search_fields = ('checksum',)
    readonly_fields = ('data',)


@admin.register(FileMetadata)
class FileMetadataAdmin(admin.ModelAdmin):
    list_display = ('debug_id', 'file_type', 'file')
    search_fields = ('file__checksum', 'debug_id', 'file_type')
