from django.core.management.base import BaseCommand

from bugsink.transaction import immediate_atomic
from files.models import File, FileMetadata


class Command(BaseCommand):
    """Delete projectless sourcemaps kept only for the project-scoping transition.

    After sourcemap metadata became project-scoped, old projectless metadata
    still works as a compatibility fallback. Run this command when you prefer
    to remove that fallback immediately and force sourcemaps to be re-uploaded
    with explicit project slugs.
    """

    help = "Delete legacy projectless sourcemaps."

    def handle(self, *args, **options):
        with immediate_atomic():
            legacy_metadata = FileMetadata.objects.filter(project__isnull=True, file_type="source_map")
            file_ids = list(legacy_metadata.values_list("file_id", flat=True))
            metadata_count = legacy_metadata.count()

            legacy_metadata.delete()

            orphan_files = File.objects.filter(id__in=file_ids, metadatas__isnull=True)
            file_count = orphan_files.count()
            orphan_files.delete()

        self.stdout.write(f"Deleted {metadata_count} legacy sourcemap metadata rows and {file_count} files.")
