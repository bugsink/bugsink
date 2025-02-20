import re
from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


class QuietConsoleEmailBackend(ConsoleEmailBackend):

    def write_message(self, message):
        msg = message.message()
        # self.stream.write("From: %s\n" % msg["From"])
        # self.stream.write("To: %s\n" % msg["To"])
        subject_header = msg["Subject"]

        # Headers may contain newlines, RFC 2822 section 2.2.3 says:
        #
        # > The process of moving from this folded multiple-line representation
        # > of a header field to its single line representation is called
        # > "unfolding". Unfolding is accomplished by simply removing any CRLF
        # > that is immediately followed by WSP. Each header field should be
        # > treated in its unfolded form for further syntactic and semantic
        # > evaluation.
        #
        # Remove those with a simple regex
        # the regex says: match newline followed by whitespace, replace with just the matched whitespace:
        subject = re.sub(r"\n(\s+)", (r"\1"), subject_header)
        self.stream.write("Email is not set up, the following was not sent: %s\n" % subject)
