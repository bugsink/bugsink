# A super-simple utility to run the WSGI application using the built-in WSGI server. The usefulness of this script is
# precisely because there is _no_ special handling of SIGINT. This means that SIGINT can be used to get a traceback
# from the application as it was when interrupted. This is useful to answer the question "why is this application
# stuck?"

import sys

from wsgiref import simple_server
from bugsink.wsgi import application


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cornless.py host:port")

    host = sys.argv[1].split(":")[0]
    port = int(sys.argv[1].split(":")[1])

    httpd = simple_server.make_server("", port, application)
    httpd.serve_forever()
