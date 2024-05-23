# A super-simple utility to run the WSGI application using the built-in WSGI server. The usefulness of this script is
# precisely because there is _no_ special handling of SIGINT. This means that SIGINT can be used to get a traceback
# from the application as it was when interrupted. This is useful to answer the question "why is this application
# stuck?"

# This version is for SQLite. sqlite3 does not support interrupts (i.e. it does not check with Python's signal handler),
# so we need to do it ourselves. This is done by calling the `interrupt()` method on the default connection.

# Because SQLite does not support interrupts, we need to spin up a new thread to run the server, so that the main thread
# can be interrupted with SIGINT. We then call the `interrupt()` method on the default connection to interrupt the
# query.

import sys
import signal
import threading

from wsgiref import simple_server
from bugsink.wsgi import application
from django.db import connections


class ImpureObject(object):
    """'impure' object in the sense that it is not purely 'object()', i.e. it allows setting attributes"""


def handle_sigint(signum, frame):
    connections["default"].connection.interrupt()
    sys.exit()


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
    # we override connections._connections to get rid of the thread-local behavior; this is necessary to be able to
    # interrupt the connection from the main thread (I wouldn't know how to do it otherwise)
    connections._connections = ImpureObject()

    signal.signal(signal.SIGINT, handle_sigint)

    t = threading.Thread(target=server)
    t.start()
    t.join()
