from django.core.mail import EmailMultiAlternatives
from django.template import Context
from django.template.loader import get_template


def send_rendered_email(subject, base_template_name, recipient_list, context=None):
    if context is None:
        context = {}

    html_content = get_template(base_template_name + ".html").render(Context(context))
    text_content = get_template(base_template_name + ".txt").render(Context(context))

    # Configure and send an EmailMultiAlternatives
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # this is settings.DEFAULT_FROM_EMAIL
        to=recipient_list,
    )

    msg.attach_alternative(html_content, "text/html")

    msg.send()
