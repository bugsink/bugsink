import argparse
import os
import sys

from django.core.management.utils import get_random_secret_key


def main():
    parser = argparse.ArgumentParser(description="Create a configuration file for the example")
    parser.add_argument("--output-file", "-o", help="Output file", default="bugsink_conf.py")
    args = parser.parse_args()

    if os.path.exists(args.output_file):
        print("Output file already exists; please remove it first")
        sys.exit(1)

    secret_key = get_random_secret_key()

    with open(args.output_file, "w") as f:
        f.write('''# auto-generated example bugsink_conf.py

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "''' + secret_key + '''"

# Alternatively, pass the SECRET_KEY as an environment variable. (although that has security implications too!)
# i.e. those may leak in shared server setups.
#
# SECRET_KEY = os.getenv("SECRET_KEY")


# See TODO in the docs
SNAPPEA = {
    "TASK_ALWAYS_EAGER": True,
    "NUM_WORKERS": 1,
}


# EMAIL_HOST = ...
# EMAIL_HOST_USER = ...
# EMAIL_HOST_PASSWORD = ...
# EMAIL_PORT = ...
# EMAIL_USE_TLS = ...

SERVER_EMAIL = DEFAULT_FROM_EMAIL = "Bugsink <bugsink@example.org>"

BUGSINK = {
    # See TODO in the docs
    # "DIGEST_IMMEDIATELY": False,

    # "MAX_EVENT_SIZE": _MEBIBYTE,
    # "MAX_EVENT_COMPRESSED_SIZE": 200 * _KIBIBYTE,
    # "MAX_ENVELOPE_SIZE": 100 * _MEBIBYTE,
    # "MAX_ENVELOPE_COMPRESSED_SIZE": 20 * _MEBIBYTE,

    # "BASE_URL": "http://bugsink:9000",  # no trailing slash
    # "SITE_TITLE": "Bugsink",  # you can customize this as e.g. "My Bugsink" or "Bugsink for My Company"
}

''')


# some thoughts that I haven't been able to squish into a short comment yet:

# 1. regarding env-variables v.s. just using a conf file: we're not religious about Twelve Factor at all, but even if we
# were 12-factor says the following (which is basically what we do):

# > Another approach to config is the use of config files which are not checked into revision control, such as
# > config/database.yml in Rails. This is a huge improvement over using constants which are checked into the code repo,
# > but still has weaknesses: it’s easy to mistakenly check in a config file to the repo; there is a tendency for config
# > files to be scattered about in different places and different formats, making it hard to see and manage all the
# > config in one place. Further, these formats tend to be language- or framework-specific.

# regarding the mentioned drawbacks: check-in is unlikely (this conf is owned by end-users, not bugsink-programmers) and
# scattering is not what we do: we have just a single file for the bugsink conf (though there are separate ones for e.g.
# gunicorn and nginx, but I'd argue that's a good thing)
#
# 2. when comparing with the auto-generated django settings, the SECRET_KEY that we generate here is less likely to be
# "automatically exposed", because it is not automatically part of the source code (checked into version control) of
# some piece of software. Still, people could check this file in, and you'd have an exposed key in that case.
#
# 3. regarding the sensitivity of this key, and storing it in the file system: I'd argue that if the server you're
# running bugsink on is compromised (and the file can be read) you have bigger problems (since the DB is also on that
# server)
