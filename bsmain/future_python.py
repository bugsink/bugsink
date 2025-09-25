# A backport of a not-yet-released version of Python's os.makedirs
#
# License: Python Software Foundation License
#
# From:
# https://github.com/python/cpython/pull/23901 as per
# https://github.com/python/cpython/pull/23901/commits/128ff8b46696c26e2cea5609cf9840b9425dcccf
#
# Note on stability: os.makedirs has not seen any changes after Python 3.7 up to
# 3.13 (3.14 is in pre-release, so unlikely to see changes). This means that the
# current code can be used as a "extra feature" drop in for at least those versions.

from os import path, mkdir, curdir


def makedirs(name, mode=0o777, exist_ok=False, *, recursive_mode=False):
    """makedirs(name [, mode=0o777][, exist_ok=False][, recursive_mode=False])

    Super-mkdir; create a leaf directory and all intermediate ones.  Works like
    mkdir, except that any intermediate path segment (not just the rightmost)
    will be created if it does not exist. If the target directory already
    exists, raise an OSError if exist_ok is False. Otherwise no exception is
    raised.  If recursive_mode is True, the mode argument will affect the file
    permission bits of any newly-created, intermediate-level directories.  This
    is recursive.

    """
    head, tail = path.split(name)
    if not tail:
        head, tail = path.split(head)
    if head and tail and not path.exists(head):
        try:
            if recursive_mode:
                makedirs(head, mode=mode, exist_ok=exist_ok,
                         recursive_mode=True)
            else:
                makedirs(head, exist_ok=exist_ok)
        except FileExistsError:
            # Defeats race condition when another thread created the path
            pass
        cdir = curdir
        if isinstance(tail, bytes):
            cdir = bytes(curdir, 'ASCII')
        if tail == cdir:           # xxx/newdir/. exists if xxx/newdir exists
            return
    try:
        mkdir(name, mode)
    except OSError:
        # Cannot rely on checking for EEXIST, since the operating system
        # could give priority to other errors like EACCES or EROFS
        if not exist_ok or not path.isdir(name):
            raise
