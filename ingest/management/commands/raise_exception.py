from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Quick and dirty command to just raise an exception and see it show up in Bugsink"

    def handle(self, *args, **options):
        try:
            self.raise_exception("Exception raised on purpose - 2")
        except Exception as e:
            # self.raise_exception("An 'accident' happened while handling the exception")
            self.raise_exception_from("We intentionally translated this into the exception", e)

    def raise_exception(self, s):
        raise Exception(s)

    def raise_exception_from(self, s, e):
        raise Exception(s) from e
