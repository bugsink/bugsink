from django.http import Http404
from django.db.backends.base.base import DEFAULT_DB_ALIAS

from bugsink.timed_sqlite_backend.base import DatabaseWrapper as TimedDatabaseWrapper

from ee.tenants.base import get_tenant_subdomain


class DatabaseWrapper(TimedDatabaseWrapper):
    """
    DatabaseWrapper w/ TENANTS

    We implement tenant-switching as a Database backend as per:
    https://forum.djangoproject.com/t/use-database-routers-to-pick-a-database-connection-for-transaction-api-by-default/29744/7

    adamchainz says:
    > I think you would instead be best doing this within a custom database backend

    roads not taken as per the forum post and other sources:
    * routers -> probably a better fit for per-model switching; will not work well with transaction(using=...);
      introduces new uglyness b/c separate snappea DB that the present solution avoids.
    * overriding settings -> no, per https://github.com/django/django/blob/888b9042b359/django/test/signals.py#L163-L171

    The basic implementation idea is that:

    [1] the model for starting connections is quite straightforward;
    * in request/response this is "near the beginning of the request", b/c CONN_MAX_AGE=0 (means: max between requests)
    * in snappea it's also clearly defined, as part of `non_failing_function` which is run in a thread
    * for the rest there is no multi-tenancy on the application level (we are single-tenant and pass in an env var)
    the above means that the thing that determines the tenant (request, snappea task) implies get_connection. Which
    means we just need to set the tenant at that moment. Which we do, via get_connection_params().

    [2] I did a manual check on the superclasses (up to base/base.py) for `NAME` and `settings_dict`, and, there are 2
    locations (only) worth overriding (from sqlite3/base.py): get_connection_params and is_in_memory_db.

    another road-not-taken: making a _backend_ per tenant, rather than switching per-connection and relying on [1]
    above. such an approach won't work because of the connection-specific state which would still be on the present
    object (the "switching" object).
    """

    def __init__(self, settings_dict, alias=DEFAULT_DB_ALIAS):
        self.tenants = settings_dict["TENANTS"]

        super().__init__({k: v for k, v in settings_dict.items() if k != "TENANTS"}, alias)

    def get_tenant(self):
        subdomain = get_tenant_subdomain()
        if subdomain is None:
            raise Exception("Cannot determine subdomain outside of request/response loop")

        if subdomain not in self.tenants:
            # shouldn't happen 'in practice' (because there would be no certificate then)
            raise Http404(f"No such site: {subdomain}.bugsink.com not found")

        return self.tenants[subdomain]

    def get_connection_params(self):
        # We just mutate the settings_dict here (the alternative is waaay too much copy-pasting), mutating back after.
        self.settings_dict["NAME"] = self.get_tenant()
        try:
            return super().get_connection_params()
        finally:
            self.settings_dict.pop("NAME", None)

    def is_in_memory_db(self):
        return False  # we _know_ we don't do multi-tenant in memory, so this is simpler than some lookup.
