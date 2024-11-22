from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


class QuietConsoleEmailBackend(ConsoleEmailBackend):

    def write_message(self, message):
        msg = message.message()
        # self.stream.write("From: %s\n" % msg["From"])
        # self.stream.write("To: %s\n" % msg["To"])
        self.stream.write("Mail not sent (no SMTP configured); Subject: %s\n" % msg["Subject"])
