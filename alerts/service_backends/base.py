import json

import requests
from requests.adapters import HTTPAdapter

from .webhook_security import parse_webhook_url, pin_url_to_ip, validate_webhook_destination
from bugsink.utils import assert_


MAX_WEBHOOK_RESPONSE_BYTES = 2000


def load_service_config(service_config_id):
    # Tasks read their webhook URL or bot token here rather than receiving it as an argument: those values are secrets,
    # and Snappea logs the arguments of every task it starts (and stores them in its queue until then).
    from alerts.models import MessagingServiceConfig

    try:
        return json.loads(MessagingServiceConfig.objects.get(id=service_config_id).config)
    except MessagingServiceConfig.DoesNotExist:
        return None


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

    def send(self, request, **kwargs):
        # We don't want to accept compressed responses: Webhook endpoints can return attacker-controlled data. A
        # vulnerability in a decompressor could become an RCE in Bugsink. And for what gain? Webhook responses should
        # typically be tiny! This is implemented by setting Accept-Encoding: identity and rejecting any non-identity
        # responses; the latter works because we can access the headers before Requests decodes the body, and we assume
        # that setting Accept-Encoding: identity is enough to get non-hostile servers to send uncompressed responses.

        request.headers["Accept-Encoding"] = "identity"
        kwargs["stream"] = True
        with super().send(request, **kwargs) as response:
            if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
                raise requests.RequestException("Compressed webhook responses are not supported.")

            # We read only those bytes into memory that we actually use (error messages are capped at 2000 bytes).
            # NOTE this pushes a bit of logic into the present point that is arguably better placed in the caller.
            response._content = response.raw.read(MAX_WEBHOOK_RESPONSE_BYTES)

        # Mark consumed only after closing: Response.close() otherwise skips closing the unread remainder.
        response._content_consumed = True
        if response.encoding is None:
            # Avoid potentially CPU-intensive encoding guesswork via charset-normalizer; "utf-8" is a good enough guess
            # for error-reponses from webhook endpoints.
            response.encoding = "utf-8"
        return response


def post_pinned(parsed, ip, *args, headers, **kwargs):
    pinned_url = pin_url_to_ip(parsed, ip)
    headers["Host"] = parsed.netloc  # netloc includes the port if present as desired for Host headers

    with requests.Session() as session:
        # Session.mount() means: for any request to pinned_url, use the given adapter
        session.mount(pinned_url, OriginalHostnameAdapter(parsed.hostname))
        # urllib3 automatically uses C-zlib (analogous issue for brotli here:
        # https://github.com/urllib3/urllib3/issues/5342)
        # TODO swap that out too.
        return session.post(pinned_url, *args, headers=headers, **kwargs)


class BaseWebhookBackend:
    @classmethod
    def safe_post(cls, webhook_url, *args, **kwargs):
        # Ensure the carefully picked values in the below cannot be accidentally overwritten caller-side; complain
        # loudly if they accidentally are.
        assert_("allow_redirects" not in kwargs)
        assert_("timeout" not in kwargs)
        headers = kwargs.pop("headers", {})
        assert_("host" not in {name.lower() for name in headers})

        parsed = parse_webhook_url(webhook_url)
        resolved_ips = validate_webhook_destination(parsed.hostname)

        # Do not follow redirects: validating only the first URL is not enough for SSRF policy enforcement.
        kwargs["allow_redirects"] = False
        kwargs["timeout"] = 5
        return post_pinned(parsed, resolved_ips[0], *args, headers=headers, **kwargs)
