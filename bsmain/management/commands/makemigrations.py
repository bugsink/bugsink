from django.core.management.commands.makemigrations import Command as OriginalCommand

from . import monkey_patch_deconstruct
monkey_patch_deconstruct()


class Command(OriginalCommand):
    pass  # no changes, except the monkey patch above
