import os
import stat
import logging
from django.template.defaultfilters import yesno as broken_yesno

from .future_python import makedirs


PRIVATE_MODE = 0o700
GLOBALLY_WRITABLE_MASK = 0o002


logger = logging.getLogger("bugsink.security")


class B108SecurityError(Exception):
    pass


def b108_makedirs(path):
    """
    Create (or validate) an app working directory with B108-style hardening against local privilege escalation:

    * Create without if-exists checks to avoid TOCTOU (makedirs(..., exist_ok=True)).

    * Final directory invariants:
      1. owned by the current uid
      2. private mode (700)

    * Path invariants (from the leaf up to the first root-owned ancestor, which is assumed to be secure):
      1. every segment is owned by the current uid
      2. no symlinks anywhere (somewhat redundant given "owned by us", but we're playing safe)

    This removes the risk of being redirected into unintended locations (symlink/rename tricks) and of leaking data
    into attacker-controlled files or directories.

    ### Backwards compatibility notes

    On already running systems, directories may have been created with laxer permissions. We simply warn about those,
    (rather than try to fix the problem) because in the general case we cannot determine where the "Bugsink boundary"
    is (e.g. we wouldn't want to mess with $HOME's permissions, which is what would happen if we simply apply the "chmod
    for current uid" rule all the way up).

    ### Further notes:

    * Our model for file-based attack vectors is simply: inside the 700 dir, you'll be good no matter what. In other
      words: no analogous checks at the file level.

    * This function implements post-verification (i.e. "in theory it's too late"); since it operates at the dir-level we
      believe "in practice it's in time" (you might trick us into writing a directory somewhere, but right after it'll
      fail the check and no files will be written)
    """
    makedirs(path, mode=PRIVATE_MODE, exist_ok=True, recursive_mode=True)
    my_uid = os.getuid()

    # the up-the-tree checks are unconditional (cheap enough, and they guard against scenarios in which an attacker
    # previously created something in the way, so we can't skip because os.makedirs says "it already exists")

    # separate from the "up-the-tree" loop b/c the target path may not be root.
    st = os.lstat(path)
    if st.st_uid != my_uid:
        raise B108SecurityError(f"Target path owned by uid other than me: {path}")

    if (st.st_mode & 0o777) != PRIVATE_MODE:
        # NOTE: warn-only to facilitate a migration doesn't undo all our hardening for post-migration/fresh installs,
        # because we still check self-ownership up to root.
        logger.warning(
            "SECURITY: Target path does not have private mode (700): %s has mode %03o", path, st.st_mode & 0o777)

    current = path
    while True:
        st = os.lstat(current)

        if st.st_uid == 0:
            # we stop checking once we reach a root-owned dir; at some level you'll "hit the system boundary" which is
            # secure by default (or it's compromised, in which case nothing helps us). We work on the assumption that
            # this boundary is correctly setup, e.g. if it's /tmp it will have the sticky bit set.
            break

        if stat.S_ISLNK(st.st_mode):
            raise B108SecurityError("Symlink in path at %s while creating %s" % (current, path))

        # if not stat.S_ISDIR(st.st_mode): not needed, because os.makedirs would trigger a FileExistsError over that

        if st.st_uid != my_uid:
            # (avoiding tripping over root is implied by the `break` in the above)
            raise B108SecurityError("Parent directory of %s not owned by my uid or root: %s" % (path, current))

        if (current != path) and (st.st_mode & GLOBALLY_WRITABLE_MASK):  # skipped for target (more strict check above)
            # note: in practice this won't trigger for "plain migrations" i.e. ones where no manual changes were made,
            # because the pre-existing code created with 0o755; still: it's a good check to have.
            #
            # note: we don't additionally check on group-writable because we don't want to make too many assumptions
            # about group setup (e.g. user private groups are common on Linux)
            logger.warning("SECURITY: Parent directory of target path %s is globally writeable: %s", path, current)

        parent = os.path.dirname(current)

        if parent == current:  # reached root
            # weird that this would not be root-owned (break above) but I'd rather not hang indefinitely for that.
            break

        current = parent


def yesno(value, arg=None):
    """
    See https://code.djangoproject.com/ticket/36579
    """
    result = broken_yesno(value, arg)
    if result is None:
        return "Maybe"
    return result
