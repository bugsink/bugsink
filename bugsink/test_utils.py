from django.test import TransactionTestCase


from phonehome.models import Installation


class TransactionTestCase25251(TransactionTestCase):
    """
    As per https://code.djangoproject.com/ticket/25251 "Any initial data loaded in migrations will only be available
    in TestCase tests and not in TransactionTestCase tests", see also:
    https://docs.djangoproject.com/en/5.1/topics/testing/overview/#rollback-emulation

    i.e. a documented footgun. And the hardest type to find, b/c the tests _do_ work in isolation (but not in batches).

    We work around this by doing the work manually here. As discovered by observing crashing tests, and by
    $ git ls-files | grep migrat | x grep object.*create
    """

    def setUp(self):
        super().setUp()
        Installation.objects.get_or_create()  # get_or_create, b/c on the first run the migration _is_ there.
