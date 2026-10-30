# Bugsink: Self-hosted Error Tracking

* [Error Tracking](https://www.bugsink.com/error-tracking/)
* [Built to self-host](https://www.bugsink.com/built-to-self-host/)
* [Sentry-SDK compatible](https://www.bugsink.com/connect-any-application/)
* [Scalable and reliable](https://www.bugsink.com/scalable-and-reliable/)

### Screenshot

![Screenshot](https://www.bugsink.com/static/images/JsonSchemaDefinitionException.5e02c1544273.png)


### Installation & docs

The **quickest way to evaluate Bugsink** is to spin up a throw-away instance using Docker:

```
docker pull bugsink/bugsink:latest

docker run \
  -e SECRET_KEY=PUT_AN_ACTUAL_RANDOM_SECRET_HERE_OF_AT_LEAST_50_CHARS \
  -e CREATE_SUPERUSER=admin@example.org:admin \
  -e PORT=8000 \
  -p 8000:8000 \
  bugsink/bugsink
```

Visit [http://localhost:8000/](http://localhost:8000/), where you'll see a login screen. The default username and password
are `admin`.

Now, you can [set up your first project](https://www.bugsink.com/docs/quickstart/) and start tracking errors.

[Detailed installation instructions](https://www.bugsink.com/docs/installation/) are on the Bugsink website.

[More information and documentation](https://www.bugsink.com/)

### OpenID Connect / SSO (this fork)

This fork adds login through any OpenID Connect provider (Keycloak, Authentik, Zitadel, Entra ID, Google, GitLab,
...). Register `{BASE_URL}/accounts/oidc/callback/` as redirect URI with your provider, then configure Bugsink. With
Docker, use these environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `OIDC_ENABLED` | `false` | Turn SSO login on |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | | Client credentials |
| `OIDC_DISCOVERY_URL` | | e.g. `https://idp.example.org/realms/main/.well-known/openid-configuration` |
| `OIDC_SCOPES` | `openid email profile` | Add your provider's groups scope if needed |
| `OIDC_CREATE_USER` | `true` | Create unknown users on first login (never with `SINGLE_USER`) |
| `OIDC_REQUIRE_VERIFIED_EMAIL` | `true` | Require the `email_verified` claim; Entra ID does not send it |
| `OIDC_GROUPS_CLAIM` | `groups` | Claim (ID token or userinfo) that lists the user's groups |
| `OIDC_REQUIRED_GROUP` | | Only members of this group may log in |
| `OIDC_ADMIN_GROUP` | | Superuser status is synced from this group on every login |
| `OIDC_ONLY` | `false` | SSO only: login redirects to the provider; signup and password reset are off |
| `OIDC_LOGIN_BUTTON_TEXT` | `Log in with SSO` | Label of the login button |

Outside Docker, set the Django settings of the same names (`OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`,
`OIDC_OP_DISCOVERY_URL`, `OIDC_RP_SCOPES`, others as above) in your `bugsink_conf.py`; see
`bugsink/settings/default.py`.

Notes:

* Users are matched by email address. Existing users, including pending invites, are linked on their first SSO login.
* With a public provider such as Google, anyone with an account there can log in. Set `OIDC_REQUIRED_GROUP` or
  `OIDC_CREATE_USER=false`, and use invites to control who gets in.
* With `OIDC_ADMIN_GROUP` set, a superuser who logs in through SSO without that group loses superuser status.
* `/accounts/login/?local=1` always shows the password form, so you can still log in when the provider is down.
* Logging out also ends the session at the provider, if the provider advertises an `end_session_endpoint`.
  Register `{BASE_URL}/accounts/login/?local=1` as post-logout redirect URI.
* Keycloak sends group paths (`/bugsink-admins`) unless you turn off "Full group path" on the groups mapper.
* Upgrading from this fork's earlier `social-auth-app-django` setup: run `python manage.py migrate social_django zero`
  *before* upgrading to drop its tables, or drop the `social_auth_*` tables manually afterwards.
