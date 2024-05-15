#!/usr/bin/env python
"""A copy of the Django-generated manage.py, but:

* in the bugsink.scripts package, such that it can be wrapped by a setuptools-installable script
* with the DJANGO_SETTINGS_MODULE set to `bugsink_conf` by default.

"""
import os
import sys


def main():
    # To maintain equivalent behavior to `python manage.py` / `python -m bugsink.scripts.manage` when running this
    # script as `bugsink-manage` we need to add the current directory to sys.path. Otherwise the Django settings module
    # will not be found if it is in the current directory.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugsink_conf')
    try:
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
