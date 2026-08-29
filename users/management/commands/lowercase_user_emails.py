from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from bugsink.transaction import immediate_atomic


User = get_user_model()


class Command(BaseCommand):
    help = (
        "Lowercases the username/email of all users; run this once before turning on USER_EMAIL_CASE_INSENSITIVE. "
        "Users that would collide after lowercasing are reported and left alone; resolve those by hand.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        with immediate_atomic():
            by_target = {}
            for user in User.objects.all():
                by_target.setdefault(user.username.lower(), []).append(user)

            colliding = [target for target, users in by_target.items() if len(users) > 1]
            if colliding:
                raise CommandError(
                    "These emails exist more than once (ignoring case); merge or delete by hand first:\n" +
                    "\n".join("  " + target for target in sorted(colliding)))

            users = [u for u in User.objects.all() if u.username != u.username.lower()]
            for user in users:
                self.stdout.write("%s -> %s" % (user.username, user.username.lower()))
                if not options["dry_run"]:
                    user.username = user.username.lower()
                    user.email = user.email.lower()
                    user.save()

            self.stdout.write("%d user(s) %s" % (len(users), "to update" if options["dry_run"] else "updated"))

