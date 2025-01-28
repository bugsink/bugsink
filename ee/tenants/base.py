from contextlib import contextmanager
import threading

local_storage = threading.local()
# we use a list to allow for nesting; even though in practice nesting will always be of the same values, this allows
# for correct tracking of the depth (such that we don't return None after push-push-pop)
local_storage.tenant_subdomain = []
global_tenant_subdomain = None  # cross-threads, for single-tenant usages (e.g. commands using os.get_env)


def set_tenant_subdomain(tenant_subdomain):
    if not hasattr(local_storage, "tenant_subdomain"):  # lazy init; I'm not 100% sure why needed
        local_storage.tenant_subdomain = []

    local_storage.tenant_subdomain.append(tenant_subdomain)


def set_global_tenant_subdomain(tenant_subdomain):
    global global_tenant_subdomain
    global_tenant_subdomain = tenant_subdomain


@contextmanager
def use_tenant_subdomain(tenant_subdomain):
    set_tenant_subdomain(tenant_subdomain)
    yield
    local_storage.tenant_subdomain.pop()


def get_tenant_subdomain():
    if global_tenant_subdomain is not None:
        return global_tenant_subdomain

    if not hasattr(local_storage, "tenant_subdomain"):  # lazy init; I'm not 100% sure why needed
        local_storage.tenant_subdomain = []

    if local_storage.tenant_subdomain == []:
        return None

    return local_storage.tenant_subdomain[-1]
