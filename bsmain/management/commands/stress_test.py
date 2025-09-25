import io
import uuid
import brotli
import threading
import signal

import time
import json
import requests

from django.core.management.base import BaseCommand

from compat.dsn import get_envelope_url, get_header_value
from bugsink.streams import compress_with_zlib, WBITS_PARAM_FOR_GZIP, WBITS_PARAM_FOR_DEFLATE
from bugsink.utils import nc_rnd
from issues.utils import get_values


def random_postfix():
    # avoids numbers, because when usedd in the type I imagine numbers may at some point be ignored in the grouping.
    random_number = nc_rnd.random()

    if random_number < 0.1:
        # 10% of the time we simply sample from 1M to create a "fat tail".
        unevenly_distributed_number = int(nc_rnd.random() * 1_000_000)
    else:
        unevenly_distributed_number = int(1 / random_number)

    return "".join([chr(ord("A") + int(c)) for c in str(unevenly_distributed_number)])


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("--threads", type=int, default=1)
        parser.add_argument("--requests", type=int, default=1)

        parser.add_argument("--dsn", nargs="+", action="extend")
        parser.add_argument("--fresh-timestamp", action="store_true")
        parser.add_argument("--fresh-trace", action="store_true")
        parser.add_argument("--tag", nargs="*", action="append")
        parser.add_argument("--compress", action="store", choices=["gzip", "deflate", "br"], default=None)
        parser.add_argument("--random-type", action="store_true", default=False)  # generate random exception type

        parser.add_argument("filename")

    def handle(self, *args, **options):
        self.stopping = False
        signal.signal(signal.SIGINT, self.handle_signal)

        compress = options['compress']

        dsns = options['dsn']

        json_filename = options["filename"]
        with open(json_filename) as f:
            data = json.loads(f.read())

        print("preparing data")
        prepared_data = {}
        timings = {}
        for i_thread in range(options["threads"]):
            prepared_data[i_thread] = {}
            for i_request in range(options["requests"]):
                prepared_data[i_thread][i_request] = self.prepare(
                    data, options, i_thread, i_request, compress)

                timings[i_thread] = []

        print("sending data")
        t0 = time.time()
        for i in range(options["threads"]):
            t = threading.Thread(target=self.loop_send_to_server, args=(
                dsns, options, compress, prepared_data[i], timings[i]))
            t.start()

        print("waiting for threads to finish")
        for t in threading.enumerate():
            if t != threading.current_thread():
                t.join()
        total_time = time.time() - t0

        self.print_stats(options["threads"], options["requests"], total_time, timings)
        print("done")

    def prepare(self, data, options, i_thread, i_request, compress):
        if "timestamp" not in data or options["fresh_timestamp"]:
            # weirdly enough a large numer of sentry test data don't actually have this required attribute set.
            # thus, we set it to something arbitrary on the sending side rather than have our server be robust
            # for it.

            # If promted, we just update the timestamp to 'now' to be able to avoid any 'ignore old stuff'
            # filters (esp. on hosted sentry when we want to see anything over there)

            data["timestamp"] = time.time()

        # in stress tests, we generally send many events, so they must be unique to be meaningful.
        data["event_id"] = uuid.uuid4().hex

        if options["fresh_trace"]:
            if "contexts" not in data:
                data["contexts"] = {}
            if "trace" not in data["contexts"]:
                data["contexts"]["trace"] = {}

            # https://develop.sentry.dev/sdk/data-model/event-payloads/span/#attributes
            # > A random hex string with a length of 16 characters. [which is 8 bytes]
            data["contexts"]["trace"]["span_id"] = nc_rnd.getrandbits(64).to_bytes(8, byteorder='big').hex()
            # > A random hex string with a length of 32 characters. [which is 16 bytes]
            data["contexts"]["trace"]["trace_id"] = nc_rnd.getrandbits(128).to_bytes(16, byteorder='big').hex()

        if options["tag"]:
            if "tags" not in data:
                data["tags"] = {}

            for tag in options["tag"]:
                tag = tag[0]  # it's a list of lists... how to prevent this is not immediately clear
                k, v = tag.split(":", 1)

                if v == "RANDOM":
                    v = "value-" + random_postfix()

                data["tags"][k] = v

        if options["random_type"]:
            values = get_values(data["exception"])
            values[0]["type"] = "Exception" + random_postfix()

        data_bytes = json.dumps(data).encode("utf-8")

        # the smallest possible envelope:
        data_bytes = (b'{"event_id":"%s"}\n{"type":"event"}\n' % (data["event_id"]).encode("utf-8") +
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

    def loop_send_to_server(self, dsns, options, compress, compressed_datas, timings):
        for compressed_data in compressed_datas.values():
            if self.stopping:
                return
            dsn = nc_rnd.choice(dsns)

            t0 = time.time()
            success = Command.send_to_server(dsn, options, compress, compressed_data)
            taken = time.time() - t0
            timings.append((success, taken))

    @staticmethod
    def send_to_server(dsn, options, compress, compressed_data):
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
                    get_envelope_url(dsn),
                    headers=headers,
                    data=compressed_data,
                    timeout=10,
                )

            elif compress == "br":
                headers["Content-Encoding"] = "br"
                response = requests.post(
                    get_envelope_url(dsn),
                    headers=headers,
                    data=compressed_data,
                    timeout=10,
                )

            response = requests.post(
                get_envelope_url(dsn),
                headers=headers,
                data=compressed_data,
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print("Error %s, %s" % (e, getattr(getattr(e, 'response', None), 'content', None)))
            return False

    def print_stats(self, threads, requests, total_time, timings):
        # flatten the dict of lists to a single list:
        all_tups = [tup for sublist in timings.values() for tup in sublist]
        all_timings = [timing for (_, timing) in all_tups]
        actual_requests = len(all_tups)

        print("==============")
        if self.stopping:
            print("Results (interrupted)")
        else:
            print("Results")
        print("==============")

        print("threads: %d" % threads)
        print("requests per thread: %d" % requests)
        print("total requests: %d" % actual_requests)
        print("total errors: %d, i.e. %d%%" % (
            len([success for (success, _) in all_tups if not success]),
            100 * len([success for (success, _) in all_tups if not success]) / len(all_tups)))
        print("total time: %.3fs" % total_time)
        print("requests per second: %.3f" % (actual_requests / total_time))

        # print the avg, mean, 90th, 95th and 99th percentiles
        print("==============")
        print("avg:   %.3fs" % (sum(all_timings) / len(all_timings)))
        print("==============")
        print("50th:    %.3fs" % sorted(all_timings)[len(all_timings) // 2])
        print("75th:    %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.75)])
        print("90th:    %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.9)])
        print("95th:    %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.95)])
        print("99th:    %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.99)])
        print("99th:    %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.99)])
        print("99.5th:  %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.995)])
        print("99.9th:  %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.999)])
        print("99.99th: %.3fs" % sorted(all_timings)[int(len(all_timings) * 0.9999)])

    def handle_signal(self, sig, frame):
        self.stopping = True
