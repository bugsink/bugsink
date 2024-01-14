import logging
import re
import os

from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template


def send_html_email_with_images(subject, html_template_name, text_template_name, recipient_list, context=None):
    if context is None:
        context = {}

    html_template_body, images = _inline_images(html_template_name)
    text_template_body = get_template(text_template_name).template.source
    _send_html_email_with_images(subject, html_template_body, text_template_body, context, images, recipient_list)


def _inline_images(template_name):
    images = []

    template = get_template(template_name)
    template_text = template.template.source

    # despite the famous SO joke https://stackoverflow.com/a/1732454/339144, in practice for known HTML, and given the
    # fact that we don't open arbitrary HTMLs but instead have control over this, using regex is perfectly fine.

    images_srcs = re.findall('src="(.*?)"', template_text)

    for i, image_src_full in enumerate(images_srcs):
        try:
            image_src = os.path.basename(image_src_full)

            img_data = open(os.path.join(settings.BASE_DIR, 'alerts/images/%s' % image_src), 'rb').read()
            template_text = template_text.replace('src="%s"' % image_src_full, 'src="cid:attached-image-%s"' % i)

            img = MIMEImage(img_data)
            img.add_header('Content-Id', '<attached-image-%s>' % i)
            img.add_header("Content-Disposition", "inline", filename=image_src)
            images.append(img)

        except FileNotFoundError:
            template_text = template_text.replace('src="%s"' % image_src_full, 'src="MISSING/%s"' % image_src_full)
            logging.warning("missing image", image_src_full)

    return template_text, images


def _send_html_email_with_images(subject, html_template_body, text_template_body, context, images, recipient_list):
    # heavily based on https://stackoverflow.com/a/1633493/339144
    html_content = Template(html_template_body).render(Context(context))
    text_content = Template(text_template_body).render(Context(context))

    # Configure and send an EmailMultiAlternatives
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # this is settings.DEFAULT_FROM_EMAIL
        to=recipient_list,
    )

    msg.attach_alternative(html_content, "text/html")

    for img in images:
        msg.attach(img)

    msg.send()
