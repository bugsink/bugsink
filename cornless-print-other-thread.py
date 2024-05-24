# A super-simple utility to run the WSGI application using the built-in WSGI server. The usefulness of this script is
# precisely because there is _no_ special handling of SIGINT. This means that SIGINT can be used to get a traceback
# from the application as it was when interrupted. This is useful to answer the question "why is this application
# stuck?"

# This version spins up a new thread to run the server, so that the main thread can be interrupted with SIGINT. This is
# useful when Python's signal-handling is not working, e.g. when running a long-running piece of C code that does not
# regularly do the call to the Python signal check. See cornless-interrupt-sqlite.py for a warning about sentry_sdk
# (observed there, but may apply here too)

# Ideas from:
# https://stackoverflow.com/questions/1032813/dump-stacktraces-of-all-active-threads

# https://stackoverflow.com/a/43242295/339144 (the idea to use a separate thread for the server comes from here, and it
# contains ideas on sqlite3 more generally)

import sys
import signal
import traceback
import threading
# import faulthandler


from wsgiref import simple_server
from bugsink.wsgi import application


def handle_sigint(signum, frame):
    print("Caught SIGINT")
    # alternatively, a more robust (but uglier) version:
    # faulthandler.dump_traceback(all_threads=True)

    traceback.print_stack(sys._current_frames()[server_thread.ident])
    sys.exit(1)


def server():
    if len(sys.argv) < 2:
        host = "127.0.0.1"
        port = 8000
    else:
        host = sys.argv[1].split(":")[0]
        port = int(sys.argv[1].split(":")[1])

    httpd = simple_server.make_server(host, port, application)
    httpd.serve_forever()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_sigint)

    server_thread = threading.Thread(target=server)
    server_thread.start()
    server_thread.join()
