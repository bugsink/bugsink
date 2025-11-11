import pprint
import re
import io
import brotli

from unittest import TestCase as RegularTestCase
from django.test import TestCase as DjangoTestCase
from django.test import override_settings
from django.core.exceptions import SuspiciousOperation
from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext
from django.db import connection
from .wsgi import allowed_hosts_error_message

from .test_utils import TransactionTestCase25251 as TransactionTestCase
from .transaction import immediate_atomic
from .volume_based_condition import VolumeBasedCondition
from .streams import (
    compress_with_zlib, GeneratorReader, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE, MaxDataReader,
    MaxDataWriter, zlib_generator, brotli_generator, BrotliError)

User = get_user_model()


def apply_n(f, n, v):
    for i in range(n):
        v = f(v)
    return v


class VolumeBasedConditionTestCase(RegularTestCase):

    def test_serialization(self):
        vbc = VolumeBasedCondition("day", 1, 100)
        self.assertEqual({"period": "day", "nr_of_periods": 1, "volume": 100}, vbc.to_dict())

        vbc2 = VolumeBasedCondition.from_dict(vbc.to_dict())
        self.assertEqual(vbc, vbc2)


class StreamsTestCase(RegularTestCase):

    def test_compress_decompress_gzip(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10

        plain_stream = io.BytesIO(myself_times_ten)
        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_GZIP))
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_GZIP))

        self.assertEqual(myself_times_ten, reader.read())

    def test_compress_decompress_deflate(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10

        plain_stream = io.BytesIO(myself_times_ten)
        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        self.assertEqual(myself_times_ten, reader.read())

    def test_compress_decompress_brotli(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10

        compressed_stream = io.BytesIO(brotli.compress(myself_times_ten))
        reader = GeneratorReader(brotli_generator(compressed_stream))

        self.assertEqual(myself_times_ten, reader.read())

    def test_decompress_brotli_tiny_bomb(self):
        # by picking something "sufficiently large" we can ensure all three code paths in brotli_generator are taken,
        # in particular the "cannot accept more input" path. (for it to be taken, we need a "big thing" on the output
        # side)
        compressed_stream = io.BytesIO(brotli.compress(b"\x00" * 15_000_000))

        size = 0
        generator = brotli_generator(compressed_stream)
        for chunk in generator:
            size += len(chunk)
        self.assertEqual(15_000_000, size)

    def test_decompress_brotli_so_called_random(self):
        compressed_stream = io.BytesIO(b"random")

        generator = brotli_generator(compressed_stream)
        size = 0
        with self.assertRaises(BrotliError):
            for chunk in generator:
                size += len(chunk)

    def test_max_data_reader(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        for i in range(25):
            self.assertEqual(b"hellohello", reader.read(10))

        with self.assertRaises(ValueError) as e:
            reader.read(10)

        self.assertEqual("Max length (250) exceeded", str(e.exception))

    def test_max_data_reader_none_ok(self):
        stream = io.BytesIO(b"hello" * 10)
        reader = MaxDataReader(250, stream)

        self.assertEqual(b"hello" * 10, reader.read(None))

    def test_max_data_reader_none_fail(self):
        stream = io.BytesIO(b"hello" * 100)
        reader = MaxDataReader(250, stream)

        with self.assertRaises(ValueError) as e:
            reader.read(None)

        self.assertEqual("Max length (250) exceeded", str(e.exception))

    def test_max_data_writer(self):
        stream = io.BytesIO()
        writer = MaxDataWriter(250, stream)

        for i in range(25):
            writer.write(b"hellohello")

        with self.assertRaises(ValueError):
            writer.write(b"hellohello")

    def test_generator_reader(self):

        def generator():
            yield b"hello "
            yield b"I am "
            yield b"a generator"

        reader = GeneratorReader(generator())

        self.assertEqual(b"hel", reader.read(3))
        self.assertEqual(b"lo ", reader.read(3))
        self.assertEqual(b"I a", reader.read(3))
        self.assertEqual(b"m a", reader.read(3))
        self.assertEqual(b" generator", reader.read(None))

    def test_generator_reader_performance(self):
        # at least one test directly for GeneratorReader; doubles as a regression test for performance issue that showed
        # up when the underlying generator yielded relatively big chunks and the read() size was small. should run
        # easily under a second.

        def yielding_big_chunks():
            yield b"x" * 500_000

        read = []
        reader = GeneratorReader(yielding_big_chunks())
        while True:
            chunk = reader.read(1)
            if chunk == b"":
                break
            read.append(chunk)


@override_settings(DEBUG_CSRF=True)
class CSRFViewsTestCase(DjangoTestCase):

    """
    Notes on (in)completeness of tests:

    we don't have a test for the case where CSRF_TRUSTED_ORIGINS is set, because we don't actually recommend using that
    (i.e. the code_path "any is_same_domain(request_netloc, host)" with an OK result)

    Further:
    $ grep code_path bugsink/tests.py  | sort  -u
                'code_path': 'CR3 - empty scheme or netloc',
                'code_path': 'CR4 - referer scheme is not https',
                'code_path': 'CR8 - is_same_domain(parsed_referer.netloc, good_referer)',
                'code_path': 'OV1 - request_origin == good_origin',
                'code_path': 'OV2 - exact match with allowed_origins_exact',
                'code_path': 'OV5 - not any is_same_domain(request_netloc, host)',
                'code_path': 'PV1 - _origin_verified',
                'code_path': 'PV2 - _check_referer',
                'code_path': 'PV3 - (just) _check_token',
                'good_referrer_code_path': 'request.get_host()',

    i.e. we test both CR and OV "until the end" (last step) but don't have tests for each and every intermediate path.
    """
    maxDiff = None

    # "relevant_settings", "META" ignored b/c trivial
    CONTEXT_KEYS = ["process_view", "origin_verified_steps", "check_referer_steps", "posted", "POST"]

    def _cnt(self, response):
        result = {k: response.context.get(k) for k in self.CONTEXT_KEYS if k in response.context}
        result["POST"] = {k: v for k, v in result["POST"].items()}  # convert QueryDict to dict for easier comparison
        return result

    def _test(self, origin, referer, secure, expected):
        response = self.client.get("/debug/csrf/")
        match = re.search(r'name="csrfmiddlewaretoken" value="(.+?)"', response.content.decode("utf-8"))
        if match is None:
            self.fail("No CSRF token found in response: %s" % response.content)
        token = match.group(1)

        headers = {}
        if origin is not None:
            headers["HTTP_ORIGIN"] = origin
        if referer is not None:
            headers["HTTP_REFERER"] = referer

        response = self.client.post("/debug/csrf/", {"csrfmiddlewaretoken": token}, secure=secure, **headers)
        self.assertEqual(200, response.status_code, response.content if response.status_code != 302 else response.url)

        expected['posted'] = True
        expected["POST"] = {"csrfmiddlewaretoken": token}

        if expected != self._cnt(response):
            result = self._cnt(response)
            del result["posted"]
            del result["POST"]
            print("We got the following...\n: %s" % pprint.pformat(result, indent=4, width=120))  # print for full copy
            self.assertEqual(expected, self._cnt(response))  # a diff for drilling down

    def test_good_origin_given(self):
        # this matches the first branch in the original code, as well as what happens in local development w/ browser
        self._test(origin="http://testserver", referer="http://testserver/debug/csrf/", secure=False, expected={
            'origin_verified_steps': {
                'request_origin': 'http://testserver',
                'good_host': 'testserver',
                'good_origin': 'http://testserver',
                'code_path': 'OV1 - request_origin == good_origin',
                '_origin_verified': True,
            },
            'process_view': {
                'request_is_secure': False,
                'code_path': 'PV1 - _origin_verified',
                '_orgin_verified': 'OK',
                '_check_token': 'OK',
                'process_view': 'OK',
            },
        })

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://subdomain.example.com"])
    def test_trusted_origin_given(self):
        # this should "probably not be needed for Bugsink, but we want to know that at least we don't crash in that
        # case"
        self._test(
            origin="https://subdomain.example.com", referer="https://subdomain.example.com/debug/csrf/", secure=False,
            expected={
                'origin_verified_steps': {
                    'request_origin': 'https://subdomain.example.com',
                    'good_host': 'testserver',
                    'good_origin': 'http://testserver',
                    'code_path': 'OV2 - exact match with allowed_origins_exact',
                    '_origin_verified': True,
                    'allowed_origins_exact': {'https://subdomain.example.com'},
                },
                'process_view': {
                    'request_is_secure': False,
                    'code_path': 'PV1 - _origin_verified',
                    '_orgin_verified': 'OK',
                    '_check_token': 'OK',
                    'process_view': 'OK',
                },
            })

    def test_funny_origin_given(self):
        # this is what you'd get if you tried to POST to the server from a different domain, or (more likely) if your
        # proxy is misconfigured and mangles the Origin header
        self._test(origin="http://funny", referer="http://funny/debug/csrf/", secure=False, expected={
            'origin_verified_steps': {
                '_origin_verified': 'FAIL',
                'allowed_origin_subdomains': {},
                'allowed_origins_exact': set(),
                'code_path': 'OV5 - not any matched_subdomain',
                'good_host': 'testserver',
                'good_origin': 'http://testserver',
                'request_netloc': 'funny',
                'request_origin': 'http://funny',
                'request_scheme': 'http',
                'matched_subdomains': [],
            },
            'process_view': {
                '_orgin_verified':
                    'FAILS WITH Origin checking failed - http://funny does not match any trusted origins.',
                'code_path': 'PV1 - _origin_verified',
                'process_view': 'FAILS at _check_origin',
                'request_is_secure': False
            },
        })

    def test_null_origin_given(self):
        # Like 'test_funny_origin_given', but with a null origin (specifically observed in the wild for misconfigured
        # proxies)
        self._test(origin="null", referer=None, secure=False, expected={
            'origin_verified_steps': {
                '_origin_verified': 'FAIL',
                'allowed_origin_subdomains': {},
                'allowed_origins_exact': set(),
                'code_path': 'OV5 - not any matched_subdomain',
                'good_host': 'testserver',
                'good_origin': 'http://testserver',
                'request_netloc': '',
                'request_origin': 'null',
                'request_scheme': '',
                'matched_subdomains': [],
            },
            'process_view': {
                '_orgin_verified':
                    'FAILS WITH Origin checking failed - null does not match any trusted origins.',
                'code_path': 'PV1 - _origin_verified',
                'process_view': 'FAILS at _check_origin',
                'request_is_secure': False
            },
        })

    def test_no_origin_referer_is_given_not_secure(self):
        self._test(origin=None, referer="http://funny/debug/csrf/", secure=False, expected={
            'process_view': {
                '_check_token': 'OK',
                'code_path': 'PV3 - (just) _check_token',
                'process_view': 'OK',
                'request_is_secure': False,
            }
        })

    def test_no_origin_referer_given_secure(self):
        self._test(origin=None, referer="https://testserver/debug/csrf/", secure=True, expected={
            'check_referer_steps': {
                '_check_referer': 'OK',
                'code_path': 'CR8 - is_same_domain(parsed_referer.netloc, good_referer)',
                'csrf_trusted_origins_hosts': [],
                'good_referer': 'testserver',
                'good_referrer_code_path': 'request.get_host()',
                'referer': 'https://testserver/debug/csrf/',
                'same_domains': [],
            },
            'process_view': {
                '_check_token': 'OK',
                'check_referer': 'OK',
                'code_path': 'PV2 - _check_referer',
                'process_view': 'OK',
                'request_is_secure': True,
            }
        })

    def test_no_origin_referer_malformed_secure(self):
        # this is what you'd get if you tried to POST to the server from a different domain, or (more likely) if your
        # proxy is misconfigured and mangles the Referer header (while not sending an Origin header at all)

        self._test(origin=None, referer='null', secure=True, expected={
            'check_referer_steps': {
                '_check_referer': 'FAILS WITH Referer checking failed - Referer is malformed.',
                'code_path': 'CR3 - empty scheme or netloc',
                'referer': 'null'
            },
            'process_view': {
                'check_referer': 'FAILS WITH Referer checking failed - Referer is malformed.',
                'code_path': 'PV2 - _check_referer',
                'process_view': 'FAILS at _check_referer',
                'request_is_secure': True,
            }
        })

    def test_no_origin_referer_given_secure_referer_insecure(self):
        # TBH not the most interesting case, but it's here for completeness
        self._test(origin=None, referer="http://funny/debug/csrf/", secure=True, expected={
            'check_referer_steps': {
                '_check_referer': 'FAILS WITH Referer checking failed - Referer is insecure while host is secure.',
                'code_path': 'CR4 - referer scheme is not https',
                'referer': 'http://funny/debug/csrf/'
            },
            'process_view': {
                'check_referer': 'FAILS WITH Referer checking failed - Referer is insecure while host is secure.',
                'code_path': 'PV2 - _check_referer',
                'process_view': 'FAILS at _check_referer',
                'request_is_secure': True,
            },
        })

    def test_no_origin_no_referer_not_secure(self):
        self._test(origin=None, referer=None, secure=False, expected={
            'process_view': {
                'request_is_secure': False,
                'code_path': 'PV3 - (just) _check_token',
                '_check_token': 'OK',
                'process_view': 'OK',
            }
        })


class SetRemoteAddrMiddlewareTestCase(RegularTestCase):

    @override_settings(X_FORWARDED_FOR_PROXY_COUNT=1)
    def test_parse_x_forwarded_for_one_proxy(self):
        from .middleware import SetRemoteAddrMiddleware

        self.assertEqual(None, SetRemoteAddrMiddleware.parse_x_forwarded_for(None))
        self.assertEqual(None, SetRemoteAddrMiddleware.parse_x_forwarded_for(""))
        self.assertEqual("1.2.3.4", SetRemoteAddrMiddleware.parse_x_forwarded_for("1.2.3.4"))

        with self.assertRaises(SuspiciousOperation):
            SetRemoteAddrMiddleware.parse_x_forwarded_for("123.123.123.123,1.2.3.4")


class ContentEncodingCheckMiddlewareTestCase(DjangoTestCase):

    def test_speak_brotli_with_arbitrary_view_fails(self):
        response = self.client.post("/", headers={"Content-Encoding": "br"})
        self.assertTrue(b"Content-Encoding handling is not supported for endpoint `home`" in response.content)


class AllowedHostsMsgTestCase(DjangoTestCase):

    def test_allowed_hosts_error_message(self):
        self.maxDiff = None

        # Note: cases for ALLOWED_HOSTS=[] are redundant because Django will refuse to start in that case.

        # ALLOWED_HOST only contains non-production domains that we typically _do not_ want to suggest in the msg
        self.assertEqual(
            "'Host: foobar' as sent by browser/proxy not in ALLOWED_HOSTS=['localhost', '127.0.0.1']. "
            "Add 'foobar' to ALLOWED_HOSTS or configure proxy to use 'Host: your.host.example'.",
            allowed_hosts_error_message("foobar", ["localhost", "127.0.0.1"]))

        # proxy misconfig: proxy speaks to "localhost"
        self.assertEqual(
            "'Host: localhost' as sent by browser/proxy not in ALLOWED_HOSTS=['testserver']. "
            "Configure proxy to use 'Host: testserver' or add the desired host to ALLOWED_HOSTS.",
            allowed_hosts_error_message("localhost", ["testserver"]))

        # proxy misconfig: proxy speaks (local) IP
        self.assertEqual(
            "'Host: 127.0.0.1' as sent by browser/proxy not in ALLOWED_HOSTS=['testserver']. "
            "Configure proxy to use 'Host: testserver' or add the desired host to ALLOWED_HOSTS.",
            allowed_hosts_error_message("127.0.0.1", ["testserver"]))

        # proxy misconfig: proxy speaks (remote) IP
        self.assertEqual(
            "'Host: 123.123.123.123' as sent by browser/proxy not in ALLOWED_HOSTS=['testserver']. "
            "Configure proxy to use 'Host: testserver' or add the desired host to ALLOWED_HOSTS.",
            allowed_hosts_error_message("123.123.123.123", ["testserver"]))

        # plain old typo ALLOWED_HOSTS-side
        self.assertEqual(
            "'Host: testserver' as sent by browser/proxy not in ALLOWED_HOSTS=['teeestserver']. "
            "Add 'testserver' to ALLOWED_HOSTS or configure proxy to use 'Host: teeestserver'.",
            allowed_hosts_error_message("testserver", ["teeestserver"]))

        # plain old typo proxy-config-side
        self.assertEqual(
            "'Host: teeestserver' as sent by browser/proxy not in ALLOWED_HOSTS=['testserver']. "
            "Add 'teeestserver' to ALLOWED_HOSTS or configure proxy to use 'Host: testserver'.",
            allowed_hosts_error_message("teeestserver", ["testserver"]))


class TestAtomicTransactions(TransactionTestCase):

    def test_only_if_needed(self):
        with CaptureQueriesContext(connection) as queries_context:
            with immediate_atomic(only_if_needed=True):
                User.objects.create(username="testuser", password="testpass")

        self.assertTrue(User.objects.filter(username="testuser").exists())
        self.assertEqual([1], [1 for q in queries_context.captured_queries if q['sql'].startswith("BEGIN")])
        self.assertEqual([1], [1 for q in queries_context.captured_queries if q['sql'].startswith("COMMIT")])

        with CaptureQueriesContext(connection) as queries_context:
            with immediate_atomic(only_if_needed=True):
                with immediate_atomic(only_if_needed=True):
                    with immediate_atomic(only_if_needed=True):
                        User.objects.create(username="testuser2", password="testpass2")

        self.assertTrue(User.objects.filter(username="testuser2").exists())
        self.assertEqual([1], [1 for q in queries_context.captured_queries if q['sql'].startswith("BEGIN")])
        self.assertEqual([1], [1 for q in queries_context.captured_queries if q['sql'].startswith("COMMIT")])
