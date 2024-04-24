# VENDORED from glitchtip, af9a700a8706f20771b005804d8c92ca95c8b072
# Changes:
# * flake8
# * max size manually changed
#
# Before 1.0 I want to probably not do this as a middleware at all, but ingest everything without unzipping and then in
# some async process do the actual unzipping (which is potentially costly)

import io
import zlib

from django.core.exceptions import RequestDataTooBig


Z_CHUNK = 1024 * 8


class ZDecoder(io.RawIOBase):
    """
    Base class for HTTP content decoders based on zlib
    See: https://github.com/eBay/wextracto/blob/9c789b1c98d95a1e87dbedfd1541a8688d128f5c/wex/http_decoder.py
    """

    def __init__(self, fp, z=None):
        self.fp = fp
        self.z = z
        self.flushed = None
        self.counter = 0

    def readable(self):
        return True

    def readinto(self, buf):
        if self.z is None:
            self.z = zlib.decompressobj()
            retry = True
        else:
            retry = False

        n = 0
        max_length = len(buf)
        # DOS mitigation - block unzipped payloads larger than max allowed size
        self.counter += 1
        if self.counter * max_length > 1_000_000_000_000:  # TODO I replaced this
            raise RequestDataTooBig()

        while max_length > 0:
            if self.flushed is None:
                chunk = self.fp.read(Z_CHUNK)
                compressed = self.z.unconsumed_tail + chunk
                try:
                    decompressed = self.z.decompress(compressed, max_length)
                except zlib.error:
                    if not retry:
                        raise
                    self.z = zlib.decompressobj(-zlib.MAX_WBITS)
                    retry = False
                    decompressed = self.z.decompress(compressed, max_length)

                if not chunk:
                    self.flushed = self.z.flush()
            else:
                if not self.flushed:
                    return n

                decompressed = self.flushed[:max_length]
                self.flushed = self.flushed[max_length:]

            buf[n:n + len(decompressed)] = decompressed
            n += len(decompressed)
            max_length = len(buf) - n

        return n


class DeflateDecoder(ZDecoder):
    """
    Decoding for "content-encoding: deflate"
    """


class GzipDecoder(ZDecoder):
    """
    Decoding for "content-encoding: gzip"
    """

    def __init__(self, fp):
        ZDecoder.__init__(self, fp, zlib.decompressobj(16 + zlib.MAX_WBITS))


class DecompressBodyMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        decode = False
        encoding = request.META.get("HTTP_CONTENT_ENCODING", "").lower()

        if encoding == "gzip":
            request._stream = GzipDecoder(request._stream)
            decode = True

        if encoding == "deflate":
            request._stream = DeflateDecoder(request._stream)
            decode = True

        if decode:
            # Since we don't know the original content length ahead of time, we
            # need to set the content length reasonably high so read generally
            # succeeds. This seems to be the only easy way for Django 1.6.
            request.META["CONTENT_LENGTH"] = "4294967295"  # 0xffffffff

            # The original content encoding is no longer valid, so we have to
            # remove the header. Otherwise, LazyData will attempt to re-decode
            # the body.
            del request.META["HTTP_CONTENT_ENCODING"]
        return self.get_response(request)
