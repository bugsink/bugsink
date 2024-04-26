import io
import uuid
import brotli
import threading

import time
import json
import requests

from django.core.management.base import BaseCommand

from compat.dsn import get_store_url, get_envelope_url, get_header_value
from bugsink.streams import compress_with_zlib, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("--threads", type=int, default=1)
        parser.add_argument("--requests", type=int, default=1)

        parser.add_argument("--dsn")
        parser.add_argument("--fresh-id", action="store_true")
        parser.add_argument("--fresh-timestamp", action="store_true")
        parser.add_argument("--compress", action="store", choices=["gzip", "deflate", "br"], default=None)
        parser.add_argument("--use-envelope", action="store_true")

        parser.add_argument("filename")

    def handle(self, *args, **options):
        compress = options['compress']
        use_envelope = options['use_envelope']
        dsn = options['dsn']

        json_filename = options["filename"]
        with open(json_filename) as f:
            data = json.loads(f.read())

        print("preparing data")
        prepared_data = {}
        for i_thread in range(options["threads"]):
            prepared_data[i_thread] = {}
            for i_request in range(options["requests"]):
                prepared_data[i_thread][i_request] = self.prepare(data, options, i_thread, i_request, compress, use_envelope)

        print("sending data")
        for i in range(options["threads"]):
            t = threading.Thread(target=self.loop_send_to_server, args=(
                dsn, options, use_envelope, compress, prepared_data[i]))
            t.start()

        print("waiting for threads to finish")
        for t in threading.enumerate():
            if t != threading.current_thread():
                t.join()
        print("done")

    def prepare(self, data, options, i_thread, i_request, compress, use_envelope):
        if "timestamp" not in data or options["fresh_timestamp"]:
            # weirdly enough a large numer of sentry test data don't actually have this required attribute set.
            # thus, we set it to something arbitrary on the sending side rather than have our server be robust
            # for it.

            # If promted, we just update the timestamp to 'now' to be able to avoid any 'ignore old stuff'
            # filters (esp. on hosted sentry when we want to see anything over there)
            data["timestamp"] = time.time()

        if options["fresh_id"]:
            data["event_id"] = uuid.uuid4().hex

        data_bytes = json.dumps(data).encode("utf-8")

        if use_envelope:
            # the smallest possible envelope:
            data_bytes = (b'{"event_id": "%s"}\n{"type": "event"}\n' % (data["event_id"]).encode("utf-8") +
                          data_bytes)

        if compress in ["gzip", "deflate"]:
            if compress == "gzip":
                wbits = WBITS_PARAM_FOR_GZIP

            elif compress == "deflate":
                wbits = WBITS_PARAM_FOR_DEFLATE

            compressed_data = compress_with_zlib(io.BytesIO(data_bytes), wbits)

        elif compress == "br":
            compressed_data = brotli.compress(data_bytes)

        else:
            compressed_data = data_bytes

        return compressed_data

    @staticmethod
    def loop_send_to_server(dsn, options, use_envelope, compress, compressed_datas):
        for compressed_data in compressed_datas.values():
            Command.send_to_server(dsn, options, use_envelope, compress, compressed_data)

    @staticmethod
    def send_to_server(dsn, options, use_envelope, compress, compressed_data):
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Sentry-Auth": get_header_value(dsn),
            }

            if compress in ["gzip", "deflate"]:
                if compress == "gzip":
                    headers["Content-Encoding"] = "gzip"

                elif compress == "deflate":
                    headers["Content-Encoding"] = "deflate"

                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=compressed_data,
                )

            elif compress == "br":
                headers["Content-Encoding"] = "br"
                response = requests.post(
                    get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                    headers=headers,
                    data=compressed_data,
                )

            response = requests.post(
                get_envelope_url(dsn) if use_envelope else get_store_url(dsn),
                headers=headers,
                data=compressed_data,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print("Error %s, %s" % (e, getattr(getattr(e, 'response', None), 'content', None)))
            return False
