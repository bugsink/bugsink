import pprint
import re
import io
import brotli

from unittest import TestCase as RegularTestCase
from django.test import TestCase as DjangoTestCase
from django.test import override_settings
from django.core.exceptions import SuspiciousOperation

from .volume_based_condition import VolumeBasedCondition
from .streams import (
    compress_with_zlib, GeneratorReader, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE, MaxDataReader,
    MaxDataWriter, zlib_generator, brotli_generator)


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

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_GZIP))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_deflate(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_brotli(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10

        compressed_stream = io.BytesIO(brotli.compress(myself_times_ten))

        result = b""
        reader = GeneratorReader(brotli_generator(compressed_stream))

        while True:
            chunk = reader.read(3)
            result += chunk
            if chunk == b"":
                break

        self.assertEqual(myself_times_ten, result)

    def test_compress_decompress_read_none(self):
        with open(__file__, 'rb') as f:
            myself_times_ten = f.read() * 10
        plain_stream = io.BytesIO(myself_times_ten)

        compressed_stream = io.BytesIO(compress_with_zlib(plain_stream, WBITS_PARAM_FOR_DEFLATE))

        result = b""
        reader = GeneratorReader(zlib_generator(compressed_stream, WBITS_PARAM_FOR_DEFLATE))

        result = reader.read(None)
        self.assertEqual(myself_times_ten, result)

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
