import requests

from .webhook_security import validate_webhook_url


class BaseWebhookBackend:
    @classmethod
    def safe_post(cls, webhook_url, *args, **kwargs):
        validate_webhook_url(webhook_url)
        # Do not follow redirects: validating only the first URL is not enough for SSRF policy enforcement.
        kwargs.setdefault("allow_redirects", False)
        return requests.post(webhook_url, *args, timeout=5, **kwargs)
