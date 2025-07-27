#!/usr/bin/env python
"""A copy of the Django-generated manage.py, but:

* in the bugsink.scripts package, such that it can be wrapped by a setuptools-installable script
* with the DJANGO_SETTINGS_MODULE set to `bugsink.settings.default` by default.

This script can be used to run Django management commands for which the settings _don't matter_.

Such commands "should probably" be extracted to be Django-independent, but that incurs its own extra work (as well as
future maintenance burden): some utility code is shared, the command utilizes the Django argv parsing, and a separate
repo _always_ brings extra overhead (e.g. for testing, CI, etc.). So this is a pragmatic solution to the problem.
"""
import os
import sys


def find_commands(management_dir):
    # explicitly enumerate Django (settings)-independent commands here (for --help)
    if 'bsmain' in management_dir:
        return ["stress_test", "send_json"]
    return []


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink.settings.default')
    try:
        # we just monkeypatch the find_commands function to return the commands which are actually settings-independent.
        import django.core.management
        django.core.management.find_commands = find_commands

        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
