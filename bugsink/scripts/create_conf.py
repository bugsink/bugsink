import argparse
import os
import sys
from pathlib import Path

from django.core.management.utils import get_random_secret_key


def main():
    parser = argparse.ArgumentParser(description="Create a configuration file.")
    parser.add_argument("--output-file", "-o", help="Output file", default="bugsink_conf.py")
    parser.add_argument(
        "--template", help="Template to use", choices=["singleserver", "local", "docker"],
        required=True)

    parser.add_argument("--port", help="Port to use in BASE_URL ; default is 8000", type=int, default=8000)
    parser.add_argument("--host", help="Host to use in BASE_URL ; default is localhost", default="localhost")
    parser.add_argument(
        "--base-dir", help="base dir for databases, snappea, and ingestion store ('singleserver' template only)",
        default="/home/bugsink")
    args = parser.parse_args()

    if os.path.exists(args.output_file):
        print("Output file already exists; please remove it first")
        sys.exit(1)

    if args.base_dir != "/home/bugsink" and args.template != "singleserver":
        print("The base-dir option is only used in the 'singleserver' template")
        sys.exit(1)

    secret_key = get_random_secret_key()
    port = str(args.port)
    host = args.host

    conf_template_dir = Path(__file__).resolve().parent.parent / "conf_templates"
    with open(conf_template_dir / (args.template + ".py.template"), "r") as f:
        template = f.read()

    body = template.\
        replace("{{ secret_key }}", secret_key).\
        replace("{{ port }}", port).\
        replace("{{ host }}", host).\
        replace("{{ base_dir }}", args.base_dir.rstrip("/"))

    with open(args.output_file, "w") as f:
        f.write(body)

    print("Configuration file created at", args.output_file)
    print("Edit this file to match your setup")


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

if __name__ == "__main__":
    main()
