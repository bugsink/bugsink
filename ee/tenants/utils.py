from contextlib import contextmanager

from .base import get_tenant_subdomain, use_tenant_subdomain


def add_tenant_subdomain_to_kwargs():
    tenant_subdomain = get_tenant_subdomain()
    assert tenant_subdomain is not None, "Must have tenant set to be able to pass this to snappea"
    return {"TENANT_SUBDOMAIN": tenant_subdomain}


@contextmanager
def pop_tenant_subdomain_from_kwargs(args, kwargs):
    if "TENANT_SUBDOMAIN" not in kwargs:
        raise Exception("To run this task I need to have a tenant subdomain, can't find that")

    tenant = kwargs.pop("TENANT_SUBDOMAIN")

    with use_tenant_subdomain(tenant):
        yield


class TenantBaseURL:
    """'lazy' evaluating drop-in for BASE_URL strings that fills in the TENANT on-demand; I've evaluated the current
    uses of BASE_URL when writing this, forcing evaulation where needed (when not covered by __add__)."""

    def __init__(self, format_domain):
        self.format_domain = format_domain

    def fmt(self):
        return self.format_domain % get_tenant_subdomain()

    def __add__(self, other):
        return self.fmt() + other

    def __str__(self):
        return self.fmt()

    def endswith(self, suffix):
        # needed b/c BASE_URL is cleaned up w/ this helper
        return self.fmt().endswith(suffix)
