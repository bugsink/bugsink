from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, models
import time


class Command(BaseCommand):
    help = "On MariaDB 10.7+, convert legacy UUID columns stored as CHAR(32) to the native UUID type. See #226."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only show what would change.")
        parser.add_argument("--yes", action="store_true", help="Do not prompt before altering tables.")

    def _require_mariadb_10_7_plus(self):
        if connection.vendor != "mysql":
            self.stdout.write("Skipping: backend is not MySQL/MariaDB.")
            return False

        if not connection.mysql_is_mariadb:
            self.stdout.write("Skipping: backend is MySQL, not MariaDB.")
            return False

        version = getattr(connection, "mysql_version", None)
        if not version or version < (10, 7):
            self.stdout.write(f"Skipping: MariaDB version {version} detected; requires >= (10, 7).")
            return False
        self.stdout.write(f"MariaDB detected: {version}. Scanning all managed models for UUIDField columns...\n\n")
        return True

    # LIKE is safe here because Django column names are alphanumeric with underscores only.
    def _column_type(self, table, column):
        qn_table = connection.ops.quote_name(table)
        sql = f"SHOW FULL COLUMNS FROM {qn_table} LIKE %s"

        with connection.cursor() as c:
            c.execute(sql, [column])
            row = c.fetchone()

        if not row:
            self.stdout.write(self.style.ERROR(f"  -> ERROR: column {column!r} not found in table {table!r}."))
            exit(1)

        return row[1].lower()  # .lower() for consistent comparisons and display (AFAICT it's lowercase anyway)

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        if not self._require_mariadb_10_7_plus():
            return

        if not dry_run and not opts["yes"]:
            self.stdout.write(self.style.WARNING("This may take a long time on large tables. Continue? [y/N]"))
            if input("> ").strip().lower() != "y":
                self.stdout.write("Cancelled.")
                return

        with connection.schema_editor() as schema_editor:
            for model in apps.get_models():
                if not model._meta.managed:
                    continue

                table = model._meta.db_table
                for field in model._meta.get_fields():
                    if not isinstance(field, models.UUIDField):
                        continue

                    # NOTE: we have no special handling for inherited fields because Bugsink has simple models only

                    column = field.column
                    db_type = self._column_type(table, column).lower()

                    self.stdout.write(
                        f"{model._meta.label}.{field.name} is of type {db_type}."
                    )

                    if db_type == "uuid":
                        self.stdout.write(" -> SKIPPING: already native UUID")
                        continue

                    if db_type != "char(32)":
                        self.stdout.write(
                            "  -> WARNING: unexpected type for a UUIDField (neither char(32) nor UUID). No action."
                        )
                        continue

                    # we let Django's schema editor handle the actual conversion; we just specify how it was in the 4.2
                    # era (under the hood); "how it is now" is already in the field definition
                    old_field = models.CharField(max_length=32, null=field.null, primary_key=field.primary_key)
                    old_field.set_attributes_from_name(field.name)  # sets field name, column etc.

                    old_field = models.CharField(
                        max_length=32,
                        null=field.null,
                        primary_key=field.primary_key,
                        unique=field.unique,
                        db_index=field.db_index,
                        db_column=field.db_column,
                    )

                    # Bind identity so Django knows which column on which model we're altering
                    old_field.name = field.name
                    old_field.attname = field.attname
                    old_field.model = model
                    old_field.concrete = True
                    old_field.column = field.column

                    if dry_run:
                        self.stdout.write("  -> DRY RUN: real run would ALTER COLUMN to native UUID.")
                        continue

                    self.stdout.write("  -> Altering ", ending="")

                    t0 = time.time()
                    schema_editor.alter_field(model, old_field, field)
                    dt = time.time() - t0

                    new_db_type = self._column_type(table, column)
                    self.stdout.write(f" to {new_db_type!r} (took {dt:.3f}s)")
