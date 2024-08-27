#!/usr/bin/env python
import subprocess
import signal
import sys


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
        self.children = []

        # I think Docker will send a SIGTERM to the main process when it wants to stop the container; SIGINT is for
        # interactive use and is also supported. SIGKILL is not handle-able, so we can't do anything about that.
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Start the server
        # Leaving stdout and stderr as None will make the output of the child processes be passed as our own.
        for args in self.parse_args():
            self.children.append(subprocess.Popen(args))

        # Check if any of the children have exited
        children_are_alive = True
        while children_are_alive:
            for child in self.children:
                if child.poll() is not None:
                    # One of the children has exited
                    children_are_alive = False

                    for other_child in self.children:
                        if other_child != child:
                            other_child.send_signal(signal.SIGTERM)

        for child in self.children:
            child.wait()

    def parse_args(self):
        """Splits our own arguments into a list of args for each of the children each, we split on "UNIFIED_WITH"."""

        # We don't want to pass the first argument, as that is the script name
        args = sys.argv[1:]

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


if __name__ == "__main__":
    ParentProcess()
