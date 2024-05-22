#!/usr/bin/env python
"""A copy of manage.py from the bugsink project, but with sys.argv[1] inserted as 'runsnappea'; when run this way the
script shows up with a meaningful name in `ps` and other such tools.
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
    sys.argv = sys.argv[:1] + ['runsnappea'] + sys.argv[1:]
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
