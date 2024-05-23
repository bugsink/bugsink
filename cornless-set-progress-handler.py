# A super-simple utility to run the WSGI application using the built-in WSGI server. The usefulness of this script is
# precisely because there is _no_ special handling of SIGINT. This means that SIGINT can be used to get a traceback
# from the application as it was when interrupted. This is useful to answer the question "why is this application
# stuck?"

# This version is for SQLite. sqlite3 does not support interrupts (i.e. it does not check with Python's signal handler),
# so we need to do it ourselves. In this case we attempt that by setting a progress handler that checks for a global
# variable that is set by the signal handler.

# This solution prints a stack trace, but then hangs for reasons I don't understand.
# (a version without a signal handler (implicit KeyboardInterrupt) works just as well / just as poorly)

import sys
import signal

from wsgiref import simple_server
from bugsink.wsgi import application
from django.db.backends.sqlite3.base import DatabaseWrapper


interrupted = False


def handle_sigint(signal, frame):
    global interrupted
    interrupted = True


signal.signal(signal.SIGINT, handle_sigint)


def stop_when_interrupted():
    global interrupted
    if interrupted:
        interrupted = False
        return -1
    return 0


def get_new_connection_with_check(self, conn_params):
    conn = original_get_new_connection(self, conn_params)
    # this is the first thing I tried; it works just fine, but so does any old python code, because any old python code
    # has PyErr_CheckSignals in its execution path.
    # conn.set_progress_handler(ctypes.pythonapi.PyErr_CheckSignals, 50)
    conn.set_progress_handler(stop_when_interrupted, 50)
    # conn.set_progress_handler(lambda: None, 50)  # the version without the signal handler (assumes signal.siganl is
    # not done, and the lambda is a moment for the regular Python signal handler, which raises keyboardInterrupt, to
    # run)
    return conn


original_get_new_connection = DatabaseWrapper.get_new_connection
DatabaseWrapper.get_new_connection = get_new_connection_with_check


if __name__ == "__main__":
    # the actual server:
    if len(sys.argv) < 2:
        host = "127.0.0.1"
        port = 8000
    else:
        host = sys.argv[1].split(":")[0]
        port = int(sys.argv[1].split(":")[1])

    httpd = simple_server.make_server(host, port, application)
    httpd.serve_forever()
