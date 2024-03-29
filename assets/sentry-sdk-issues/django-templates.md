When running with `DEBUG=True`, the code context for TemplateSyntaxError is mangled in 2 ways:

* There are trailing \n in the lines
* The code is doubly escaped

This is because:

* In Django, `./django/template/base.py`, in `get_exception_info()`, the lines are escaped.
    This is possibly an error? I've removed that code and it renders just fine?

* In the Sentry SDK, these values are simply copied:
    See `./sentry_sdk/integrations/django/templates.py`,  `if hasattr(exc_value, "template_debug")`
