from bsmain.forms import AuthTokenForm
from bugsink.api_capabilities import CAPABILITY_FIELD_NAMES

OFFERED_CAPABILITIES = [
    "projects:read", "issues:read", "events:read", "issues:comment",
    "issues:triage", "projects:manage", "teams:read",
]
PRECHECKED_CAPABILITIES = ["projects:read", "issues:read", "events:read", "issues:comment"]


class OAuthConsentForm(AuthTokenForm):
    def __init__(self, *args, client_name, **kwargs):
        super().__init__(*args, **kwargs)
        # disabled fields keep their initial value and make the parent's clean() behave without them
        self.fields["is_user_bound"].disabled = True
        self.initial["is_user_bound"] = True
        for capability, field_name in CAPABILITY_FIELD_NAMES.items():
            if capability not in OFFERED_CAPABILITIES:
                self.fields[field_name].disabled = True
        self.initial["description"] = f"{client_name} (MCP)"[:255]
        for capability in PRECHECKED_CAPABILITIES:
            self.initial[CAPABILITY_FIELD_NAMES[capability]] = True

    @property
    def capability_groups(self):
        groups = {}
        for capability in OFFERED_CAPABILITIES:
            prefix, name = capability.split(":", 1)
            groups.setdefault(prefix, []).append({"name": name, "field": self[CAPABILITY_FIELD_NAMES[capability]]})
        return [{"prefix": prefix, "capabilities": capabilities} for prefix, capabilities in groups.items()]

    def selected_capabilities(self):
        return sorted(c for c in OFFERED_CAPABILITIES if self.cleaned_data.get(CAPABILITY_FIELD_NAMES[c]))
