from urllib.parse import urlparse

from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template


def send_rendered_email(subject, base_template_name, recipient_list, context=None):
    if context is None:
        context = {}

    html_content = get_template(base_template_name + ".html").render(context)
    text_content = get_template(base_template_name + ".txt").render(context)

    # Configure and send an EmailMultiAlternatives
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # this is settings.DEFAULT_FROM_EMAIL
        to=recipient_list,
    )

    msg.attach_alternative(html_content, "text/html")

    msg.send()


def deduce_allowed_hosts(base_url):
    url = urlparse(base_url)
    if url.hostname == "localhost":
        # Allow all hosts when running locally; useful to avoid understanding why 127.0.0.1:8000 is not allowed when
        # localhost:8000 is.
        return ["*"]
    return [url.hostname]


def understandable_json_error(e):
    # When a JSON schema contains many anyOfs, the default error message does not contain any useful information
    # (despite containing a lot of information). This function recursively traverses the "context" to extract, what I
    # found in Sept 2024, to be the most useful information.

    if e.context == []:
        if e.message.endswith("is not of type 'null'"):
            # when you implement 'nullable' as an anyOf with null, this will be half of the error messages, but not the
            # useful half. So we just ignore it.
            return ""

        # no more children, we're at the node, let's return the actually-interesting information
        return ("%s: " % e.json_path) + e.message

    # we have children, let's recurse
    return "\n".join([s for s in [understandable_json_error(suberror) for suberror in e.context] if s != ""])
