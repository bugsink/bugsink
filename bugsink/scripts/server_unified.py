#!/usr/bin/env python
import subprocess
import signal
import sys
import os
from time import sleep


class ParentProcess:

    def __init__(self):
        """
        This script starts both the server and snappea as children of a single process.

        * Output of the children is passed as our own.
        * Any (relevant) signals we receive are passed to all the children.
        * When either of the children exits, a signal is sent to the other child to terminate it.
        * The script waits for both children to exit before exiting itself.

        The script is written to be able to run the two parts of Bugsink in a single Docker container. It may, however,
        be useful in other contexts as well, i.e. for [developer] ergonomics when running in a terminal.
        """
        print("Server-unified starting with pid", os.getpid())

        self.pre_start()

        self.children = []

        # I think Docker will send a SIGTERM to the main process when it wants to stop the container; SIGINT is for
        # interactive use and is also supported. SIGKILL is not handle-able, so we can't do anything about that.
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        try:
            self.start_children()
            self.connect_childrens_fates()
        finally:
            for child in self.children:
                child.wait()

    def pre_start(self):
        # I'd rather this was not needed, I don't know how to do that in a way that works with Docker: The recommended
        # way of running CMD in a Dockerfile is to use the exec form, which doesn't allow for running a script that does
        # some setup before starting the main process, i.e. doesn't allow for '&&'.  Recommended here means: warning
        # about signal-handling if you choose the other form.

        for args in self.get_pre_start_command_args(sys.argv):
            print("Server-unified 'pre-start' process:", " ".join(args))
            proc = subprocess.run(args)
            if proc.returncode != 0:
                sys.exit(proc.returncode)

    def start_children(self):
        # Leaving stdout and stderr as None will make the output of the child processes be passed as our own.
        for args in self.get_parallel_command_args(sys.argv):
            try:
                child = subprocess.Popen(args)
            except Exception:
                # Print is a bit superflous here, as the exception will be printed anyway by the raise
                # print("Server-unified failed to start process:", " ".join(args), "(%s)" % e)
                self.terminate_children()
                raise

            print("Server-unified started process %s:" % child.pid, " ".join(args))
            self.children.append(child)

    def terminate_children(self, except_child=None):
        for child in self.children:
            if child != except_child:
                child.send_signal(signal.SIGTERM)

    def connect_childrens_fates(self):
        # Check if any of the children have exited
        children_are_alive = True
        while children_are_alive:
            sleep(.05)  # Sleep in the busy loop to avoid 100% CPU usage

            for child in self.children:
                if child.poll() is not None:
                    # One of the children has exited
                    children_are_alive = False
                    self.terminate_children(except_child=child)

    @classmethod
    def get_pre_start_command_args(self, argv):
        """Splits our own arguments into a list of args for each of the pre-start commands, we split on "AMP_AMP"."""

        # We don't want to pass the first argument, as that is the script name
        args = argv[1:]

        result = []
        this = []
        for arg in args:
            if arg == "AMP_AMP":
                # AMP_AMP serves as a terminator here, i.e. we only add-to-result when we encounter it, the last bit
                # is never addeded (it will be dealt with as the set of parallel commands)
                result.append(this)
                this = []
            else:
                this.append(arg)

        return result

    @classmethod
    def get_parallel_command_args(self, argv):
        """Splits our own arguments into a list of args for each of the children each, we split on "UNIFIED_WITH"."""

        # We don't want to pass the first argument, as that is the script name
        args = argv[1:]

        while "AMP_AMP" in args:
            args = args[args.index("AMP_AMP") + 1:]

        result = [[]]
        for arg in args:
            if arg == "UNIFIED_WITH":
                result.append([])
            else:
                result[-1].append(arg)

        return result

    def signal_handler(self, signum, frame):
        # we resist the urge to print here, as this is discouraged in signal handlers
        for child in self.children:
            child.send_signal(signum)


def main():
    ParentProcess()


if __name__ == "__main__":
    main()
