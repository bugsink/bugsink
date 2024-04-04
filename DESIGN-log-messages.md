We support Logging as good as we can, because we've taken the approach of being compatible with Sentry clients, and those occassionally send Log messages. We don't want to be confusing in that case. Having said that:

Bugsink is about Error handling, not about arbitrary logging. Looking at the competition (Sentry, GlicthTip), I don't think log messages show up particularly strong there: because the message is lifted to the main title element, and because there is barely any info to show (certainly no stacktrace), they are in fact more confusing than anything (we've at least taken a more explicit approach, of putting some general "Log Message" at the top, and showing the message where the exception messages are generally shown). Perhaps that logging shines when you see it through the lens of transactions (then again: perhaps not -- maybe they're just chasing the trend of "log everythign").

One further question: I see a lot of "error" levels in the messages as sent with some quick tests... even when those messages had lower log-levels.

