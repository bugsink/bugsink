import requests
from requests.adapters import HTTPAdapter

from .webhook_security import parse_webhook_url, pin_url_to_ip, validate_webhook_destination


class OriginalHostnameAdapter(HTTPAdapter):
    # Request hook that preserves HTTPS hostname handling by using the original webhook hostname.
    def __init__(self, original_hostname):
        self.original_hostname = original_hostname
        super().__init__()

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        if host_params["scheme"] == "https":
            pool_kwargs["server_hostname"] = self.original_hostname
            pool_kwargs["assert_hostname"] = self.original_hostname  # explicit is better (default: use server_hostname)
        return host_params, pool_kwargs


def post_pinned(parsed, ip, *args, headers, **kwargs):
    pinned_url = pin_url_to_ip(parsed, ip)
    headers["Host"] = parsed.netloc  # netloc includes the port if present as desired for Host headers

    with requests.Session() as session:
        # Session.mount() means: for any request to pinned_url, use the given adapter
        session.mount(pinned_url, OriginalHostnameAdapter(parsed.hostname))
        return session.post(pinned_url, *args, headers=headers, **kwargs)


class BaseWebhookBackend:
    @classmethod
    def safe_post(cls, webhook_url, *args, **kwargs):
        # Ensure the carefully picked values in the below cannot be accidentally overwritten caller-side; complain
        # loudly if they accidentally are.
        assert "allow_redirects" not in kwargs
        assert "timeout" not in kwargs
        headers = kwargs.pop("headers", {})
        assert "host" not in {name.lower() for name in headers}

        parsed = parse_webhook_url(webhook_url)
        resolved_ips = validate_webhook_destination(parsed.hostname)

        # Do not follow redirects: validating only the first URL is not enough for SSRF policy enforcement.
        kwargs["allow_redirects"] = False
        kwargs["timeout"] = 5
        return post_pinned(parsed, resolved_ips[0], *args, headers=headers, **kwargs)
