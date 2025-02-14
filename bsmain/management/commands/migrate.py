import time
from django.core.management.commands.migrate import Command as DjangoMigrateCommand


class Command(DjangoMigrateCommand):
    # We override the default Django migrate command to add the elapsed time for each migration. (This could in theory
    # be achieved by using `--verbosity 2`, but that would also print a lot of other information that we don't want to
    # show.)
    #
    # We care more about the elapsed time for each migration than the average Django user because sqlite takes such a
    # prominent role in our architecture, and because migrations are run out of our direct control ("self hosted").
    #
    # AFAIU, "just dropping a file called migrate.py in one of our apps" is good enough to be the override (and if it
    # isn't, it's not critical, since all we do is add a bit more info to the output).

    def migration_progress_callback(self, action, migration=None, fake=False):
        # Django 4.2's method, with a single change

        if self.verbosity >= 1:
            compute_time = True  # this is the overridden line w.r.t. the original method
            if action == "apply_start":
                if compute_time:
                    self.start = time.monotonic()
                self.stdout.write("  Applying %s..." % migration, ending="")
                self.stdout.flush()
            elif action == "apply_success":
                elapsed = (
                    " (%.3fs)" % (time.monotonic() - self.start) if compute_time else ""
                )
                if fake:
                    self.stdout.write(self.style.SUCCESS(" FAKED" + elapsed))
                else:
                    self.stdout.write(self.style.SUCCESS(" OK" + elapsed))
            elif action == "unapply_start":
                if compute_time:
                    self.start = time.monotonic()
                self.stdout.write("  Unapplying %s..." % migration, ending="")
                self.stdout.flush()
            elif action == "unapply_success":
                elapsed = (
                    " (%.3fs)" % (time.monotonic() - self.start) if compute_time else ""
                )
                if fake:
                    self.stdout.write(self.style.SUCCESS(" FAKED" + elapsed))
                else:
                    self.stdout.write(self.style.SUCCESS(" OK" + elapsed))
            elif action == "render_start":
                if compute_time:
                    self.start = time.monotonic()
                self.stdout.write("  Rendering model states...", ending="")
                self.stdout.flush()
            elif action == "render_success":
                elapsed = (
                    " (%.3fs)" % (time.monotonic() - self.start) if compute_time else ""
                )
                self.stdout.write(self.style.SUCCESS(" DONE" + elapsed))
