from django.test import TestCase
from .tasks import _make_message_body


class PhoneHomeTests(TestCase):

    def test_make_message_body(self):
        # simple "does not crash" test (at least tests the various database getter code paths don't crash)
        _make_message_body()
